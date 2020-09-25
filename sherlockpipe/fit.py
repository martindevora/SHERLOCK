# from __future__ import print_function, absolute_import, division
import multiprocessing
import re
import shutil
import types
from pathlib import Path

import allesfitter
import numpy as np
import matplotlib
import yaml
from argparse import ArgumentParser
from sherlockpipe.star.HabitabilityCalculator import HabitabilityCalculator
import pandas as pd
import os
from os import path


resources_dir = path.join(path.dirname(__file__))


class Fitter:
    def __init__(self, object_dir, only_initial):
        self.args = types.SimpleNamespace()
        self.args.noshow = True
        self.args.north = False
        self.args.o = True
        self.args.auto = True
        self.args.save = True
        self.args.nickname = ""  # TODO do we set the sherlock id?
        self.args.FFI = False  # TODO get this from input
        self.args.targetlist = "best_signal_latte_input.csv"
        self.args.new_path = ""  # TODO check what to do with this
        self.object_dir = os.getcwd() if object_dir is None else object_dir
        self.latte_dir = str(Path.home()) + "/.sherlockpipe/latte/"
        if not os.path.exists(self.latte_dir):
            os.mkdir(self.latte_dir)
        self.data_dir = self.object_dir
        self.only_initial = only_initial

    def fit(self, candidate_df, star_df, cpus, allesfit_dir):
        candidate_row = candidate_df.iloc[0]
        star_file = allesfit_dir + "/params_star.csv"
        params_file = allesfit_dir + "/params.csv"
        settings_file = allesfit_dir + "/settings.csv"
        if candidate_row["number"] is None or np.isnan(candidate_row["number"]):
            lc_file = "/" + candidate_row["lc"]
        else:
            lc_file = "/" + str(candidate_row["number"]) + "/lc_" + str(candidate_row["curve"]) + ".csv"
        shutil.copyfile(self.object_dir + lc_file, allesfit_dir + "/lc.csv")
        shutil.copyfile(self.object_dir + "/params_star.csv", star_file)
        shutil.copyfile(resources_dir + "/resources/allesfitter/params.csv", params_file)
        shutil.copyfile(resources_dir + "/resources/allesfitter/settings.csv", settings_file)
        # TODO replace sherlock properties from allesfitter files
        # TODO only use params_star when the star mass or radius was not assumed
        with open(settings_file, 'r+') as f:
            text = f.read()
            text = re.sub('\\${sherlock:cores}', str(cpus), text)
            text = re.sub('\\${sherlock:name}', str(candidate_row["name"]), text)
            f.seek(0)
            f.write(text)
            f.truncate()
        with open(params_file, 'r+') as f:
            text = f.read()
            text = re.sub('\\${sherlock:t0}', str(candidate_row["t0"]), text)
            text = re.sub('\\${sherlock:period}', str(candidate_row["period"]), text)
            rp_rs = candidate_row["rp_rs"] if candidate_row["rp_rs"] != "-" else 0.1
            text = re.sub('\\${sherlock:rp_rs}', str(rp_rs), text)
            sum_rp_rs_a = (candidate_row["rp_rs"] + star_df.iloc[0]['R_star']) / candidate_row["a"] * 0.00465047 \
                if candidate_row["rp_rs"] != "-" else 0.2
            text = re.sub('\\${sherlock:sum_rp_rs_a}', str(sum_rp_rs_a), text)
            text = re.sub('\\${sherlock:name}', str(candidate_row["name"]), text)
            f.seek(0)
            f.write(text)
            f.truncate()
        allesfitter.show_initial_guess(allesfit_dir)
        if not self.only_initial:
            allesfitter.ns_fit(allesfit_dir)
            allesfitter.ns_output(allesfit_dir)


if __name__ == '__main__':
    ap = ArgumentParser(description='Vetting of Sherlock objects of interest')
    ap.add_argument('--object_dir',
                    help="If the object directory is not your current one you need to provide the ABSOLUTE path",
                    required=False)
    ap.add_argument('--candidate', type=int, default=None, help="The candidate signal to be used.", required=False)

    ap.add_argument('--only_initial', dest='only_initial', action='store_true',
                        help="Whether to only run an initial guess of the transit")
    ap.set_defaults(only_initial=False)
    ap.add_argument('--cpus', type=int, default=None, help="The number of CPU cores to be used.", required=False)
    ap.add_argument('--properties', help="The YAML file to be used as input.", required=False)
    args = ap.parse_args()
    fitter = Fitter(args.object_dir, args.only_initial)
    index = 0
    fitting_dir = fitter.data_dir + "/fit_" + str(index)
    while os.path.exists(fitting_dir) or os.path.isdir(fitting_dir):
        fitting_dir = fitter.data_dir + "/fit_" + str(index)
        index = index + 1
    os.mkdir(fitting_dir)
    fitter.data_dir = fitter.object_dir
    star_df = pd.read_csv(fitter.data_dir + "/params_star.csv")
    if args.candidate is None:
        user_properties = yaml.load(open(args.properties))
        candidate = pd.DataFrame(columns=['id', 'period', 't0', 'cpus', 'rp_rs', 'a', 'number', 'name', 'lc'])
        candidate = candidate.append(user_properties["planet"], ignore_index=True)
        user_star_df = pd.DataFrame(columns=['R_star', 'M_star'])
        if "star" in user_properties and user_properties["star"] is not None:
            user_star_df = user_star_df.append(user_properties["star"], ignore_index=True)
            if user_star_df.iloc[0]["R_star"] is not None:
                star_df.at[0, "R_star"] = user_star_df.iloc[0]["R_star"]
            if user_star_df.iloc[0]["M_star"] is not None:
                star_df.at[0, "M_star"] = user_star_df.iloc[0]["M_star"]
            if ("a" not in user_properties["planet"] or user_properties["planet"]["a"] is None)\
                    and star_df.iloc[0]["M_star"] is not None and not np.isnan(star_df.iloc[0]["M_star"]):
                candidate.at[0, "a"] = HabitabilityCalculator() \
                    .calculate_semi_major_axis(user_properties["planet"]["period"],
                                               user_properties["star"]["M_star"])
            elif ("a" not in user_properties["planet"] or user_properties["planet"]["a"] is None)\
                    and (star_df.iloc[0]["M_star"] is None or np.isnan(star_df.iloc[0]["M_star"])):
                raise ValueError("Cannot guess semi-major axis without star mass.")
        if candidate.iloc[0]["a"] is None or np.isnan(candidate.iloc[0]["a"]):
            raise ValueError("Semi-major axis is neither provided nor inferred.")
        if candidate.iloc[0]["name"] is None:
            raise ValueError("You need to provide a name for your candidate.")
        if candidate.iloc[0]["lc"] is None:
            raise ValueError("You need to provide a light curve relative path for your candidate.")
        cpus = user_properties["settings"]["cpus"]
    else:
        candidate_selection = int(args.candidate)
        candidates = pd.read_csv(fitter.object_dir + "/candidates.csv")
        if candidate_selection < 1 or candidate_selection > len(candidates.index):
            raise SystemExit("User selected a wrong candidate number.")
        candidates = candidates.rename(columns={'Object Id': 'TICID'})
        candidate = candidates.iloc[[candidate_selection - 1]]
        candidate['number'] = [candidate_selection]
        candidate['name'] = 'SOI_' + candidate['number'].astype(str)
        if args.cpus is None:
            cpus = multiprocessing.cpu_count() - 1
        else:
            cpus = args.cpus
        print("Selected signal number " + str(candidate_selection))
    fitter.fit(candidate, star_df, cpus, fitting_dir)
