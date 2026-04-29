import numpy as np
import pandas as pd
import time
import matplotlib.pyplot as plt
import pprint
from collections import Counter
from IPython.display import Image
from IPython.core.display import HTML

from ortools.sat.python import cp_model
import json, pickle
import random

maxtimeinsec=160
batch_size = 100

with open('profs.pkl', 'rb') as file:
    profs = pickle.load(file)
classes = sorted(list(set(cl for teacher in profs for cl in profs[teacher]['classi'])))

for j in profs.keys():
    print([j,profs[j]])
    print(' ')
#exit()
# Compute total hours for each prof
for prof in profs:
    profs[prof]['tot_ore'] = sum(profs[prof]['classi'][cl][subj]['ore'] for cl in profs[prof]['classi'] for subj in profs[prof]['classi'][cl])

materiemax={'inglese':2, 'Matematica':2, 'fisica':2, 'italiano':2, 'latino':2}

rangedays=range(1,7)
rangetimes=range(8,14)

# All prof-class pairs
all_pairs = [(prof, cl) for prof in profs for cl in profs[prof]['classi']]
random.shuffle(all_pairs)

import math
num_batches = math.ceil(len(all_pairs) / batch_size)
print(f"Estimated number of batches: {num_batches}")
import time
time.sleep(5)

# Class to profs mapping
class_profs = {cl: set() for cl in classes}
for prof in profs:
    for cl in profs[prof]['classi']:
        class_profs[cl].add(prof)

current_hints = {}
included_pairs = set()
batchn=1

def check_feasibility(model, message, time_limit=10):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.log_search_progress = True
    status = solver.Solve(model)
    print(f"Status after {message}: {status}")
    if status == cp_model.INFEASIBLE:
        print(f"Infeasible after adding {message}")
        print(solver.ResponseStats())
        exit()
    elif status == cp_model.UNKNOWN:
        print(f"Unknown status (可能 timeout) after {message}")
    else:
        print(f"Feasible after adding {message}")
    return status

def add_lecture_variables(model, included_pairs, profs, rangedays, rangetimes):
    lectures = {}
    for prof, cl in included_pairs:
        for subj in profs[prof]['classi'][cl]:
            for day in rangedays:
                for hour in rangetimes:
                    lectures[(prof, cl, subj, day, hour)] = model.NewBoolVar(f'prof{prof}_{cl}_{subj}_{day}_{hour}')
    return lectures

def add_gliberi_variables(model, full_profs, profs):
    gliberi = {}
    for prof in full_profs:
        gliberi[prof] = {'days': profs[prof]['glibero'], 'choice': [model.NewBoolVar(f'prof{prof}_first'), model.NewBoolVar(f'prof{prof}_second'), model.NewBoolVar(f'prof{prof}_third')]}
        model.Add(sum(gliberi[prof]['choice'])==1)
    return gliberi

def add_hour_constraints(model, lectures, included_pairs, profs, rangedays, rangetimes):
    for prof, cl in included_pairs:
        for subj in profs[prof]['classi'][cl]:
            myhours = profs[prof]['classi'][cl][subj]['ore']
            model.Add(sum(lectures[(prof, cl, subj, day, hour)] for day in rangedays for hour in rangetimes) == myhours)

def add_free_days_constraints(model, lectures, full_profs, profs, gliberi, rangedays, rangetimes):
    for prof in full_profs:
        for cl in profs[prof]['classi']:
            for subj in profs[prof]['classi'][cl]:
                for day in rangedays:
                    sum_day = sum(lectures[(prof, cl, subj, day, hour)] for hour in rangetimes)
                    if day == gliberi[prof]['days'][0]:
                        model.Add(sum_day == 0).OnlyEnforceIf(gliberi[prof]['choice'][0])
                    elif day == gliberi[prof]['days'][1]:
                        model.Add(sum_day == 0).OnlyEnforceIf(gliberi[prof]['choice'][1])
                    elif day==gliberi[prof]['days'][1]:
                        model.Add(sum_day == 0).OnlyEnforceIf(gliberi[prof]['choice'][2])
def add_no_holes_constraints(model, lectures, full_classes, class_profs, profs, included_pairs, rangedays, rangetimes):
    for cl in full_classes:
        #continue
        for day in rangedays:
            accums = []
            for hour in rangetimes:
                accum = sum(lectures[(prof, cl, subj, day, hour)] for prof in class_profs[cl] if (prof, cl) in included_pairs for subj in profs[prof]['classi'][cl])
                accums.append(accum)
            model.Add(accums[0] == 1)
            for i in range(len(accums) - 1):
                model.Add(accums[i + 1] <= accums[i])

def add_no_overlap_constraints(model, lectures, included_pairs, profs, class_profs, rangedays, rangetimes):
    for day in rangedays:
        ##continue
        for hour in rangetimes:
            # Prof overlap
            for prof in set(p for p, _ in included_pairs):
                accum = sum(lectures[(prof, cl, subj, day, hour)] for cl in profs[prof]['classi'] if (prof, cl) in included_pairs for subj in profs[prof]['classi'][cl])
                model.Add(accum <= 1)
            # Class overlap
            for cl in set(c for _, c in included_pairs):
                accum = sum(lectures[(prof, cl, subj, day, hour)] for prof in class_profs[cl] if (prof, cl) in included_pairs for subj in profs[prof]['classi'][cl])
                model.Add(accum <= 1)

def add_consecutive_constraints(model, lectures, classes, profs, included_pairs, rangedays, rangetimes):
    runner = 0
    accumprimmat = 0
    for cl in classes:
        accummat = []
        accumginn = []
        mat_included = any(cl in profs[prof]['classi'] and 'Matematica' in profs[prof]['classi'][cl] and (prof, cl) in included_pairs for prof in profs)
        ginn_included = any(cl in profs[prof]['classi'] and 'Scienzemotorie' in profs[prof]['classi'][cl] and (prof, cl) in included_pairs for prof in profs)
        for prof in profs:
            if cl in profs[prof]['classi'] and (prof, cl) in included_pairs:
                if 'Matematica' in profs[prof]['classi'][cl]:
                    for day in rangedays:
                        for itime in range(8, 12):
                            a = model.NewBoolVar(f'cons{runner}')
                            runner += 1
                            model.AddBoolAnd([lectures[(prof, cl, 'Matematica', day, itime)], lectures[(prof, cl, 'Matematica', day, itime + 1)]]).OnlyEnforceIf(a)
                            model.AddBoolOr([lectures[(prof, cl, 'Matematica', day, itime)].Not(), lectures[(prof, cl, 'Matematica', day, itime + 1)].Not()]).OnlyEnforceIf(a.Not())
                            accummat.append(a)
                        for itime in rangetimes:
                            accumprimmat += lectures[(prof, cl, 'Matematica', day, itime)] * (itime - 7)
                if 'Scienzemotorie' in profs[prof]['classi'][cl]:
                    for day in rangedays:
                        for itime in range(8, 12):
                            c = model.NewBoolVar(f'cons{runner}')
                            runner += 1
                            model.AddBoolAnd([lectures[(prof, cl, 'Scienzemotorie', day, itime)], lectures[(prof, cl, 'Scienzemotorie', day, itime + 1)]]).OnlyEnforceIf(c)
                            model.AddBoolOr([lectures[(prof, cl, 'Scienzemotorie', day, itime)].Not(), lectures[(prof, cl, 'Scienzemotorie', day, itime + 1)].Not()]).OnlyEnforceIf(c.Not())
                            accumginn.append(c)
        if mat_included:
            model.AddBoolOr(accummat)
        if ginn_included:
            model.AddBoolOr(accumginn)
    return accumprimmat

def add_uniform_class_penalties(model, lectures, classes, profs, included_pairs, rangedays, rangetimes):
    totpenaltore = 0
    runner3 = 0
    for cl in classes:
        for prof in profs:
            if cl in profs[prof]['classi'] and (prof, cl) in included_pairs:
                for subj in profs[prof]['classi'][cl]:
                    thisore = profs[prof]['classi'][cl][subj]['ore']
                    for day in rangedays:
                        howmany = [lectures[(prof, cl, subj, day, itime)] for itime in rangetimes]
                        iore = model.NewIntVar(-40, 40, f'varore{runner3}')
                        iore2 = model.NewIntVar(0, 1600, f'var2ore{runner3}')
                        runner3 += 1
                        model.Add(iore == sum(howmany) * 6 - thisore)
                        model.AddMultiplicationEquality(iore2, [iore, iore])
                        totpenaltore += iore2
    return totpenaltore

def add_uniform_prof_penalties(model, lectures, full_profs, profs, rangedays, rangetimes):
    totpenaltoreprof = 0
    runner4 = 0
    for prof in full_profs:
        thisore = profs[prof]['tot_ore']
        for day in rangedays:
            howmany = [lectures[(prof, cl, subj, day, itime)] for cl in profs[prof]['classi'] for subj in profs[prof]['classi'][cl] for itime in rangetimes]
            ioreprof = model.NewIntVar(-40, 40, f'varoreprof{runner4}')
            iore2prof = model.NewIntVar(0, 1600, f'var2oreprof{runner4}')
            runner4 += 1
            model.Add(ioreprof == sum(howmany) * 6 - thisore)
            model.AddMultiplicationEquality(iore2prof, [ioreprof, ioreprof])
            totpenaltoreprof += iore2prof
    return totpenaltoreprof

def add_max_hours_constraints(model, lectures, classes, profs, included_pairs, rangedays, rangetimes):
    for cl in classes:
        for day in rangedays:
            for prof in profs:
                if cl in profs[prof]['classi'] and (prof, cl) in included_pairs:
                    accum = []
                    for subj in profs[prof]['classi'][cl]:
                        temp = [lectures[(prof, cl, subj, day, itime)] for itime in rangetimes]
                        model.Add(sum(temp) <= 2)
                        accum.extend(temp)
                    model.Add(sum(accum) <= 3)

def add_buche_penalties(model, lectures, full_profs, profs, rangedays, rangetimes):
    accumbuchi = 0
    cinqueoretot = 0
    runner2 = 0
    for prof in full_profs:
        accumbuchiprof = 0
        cinqueoreprof = 0
        for day in rangedays:
            hasit = []
            for itime in rangetimes:
                haora = [lectures[(prof, cl, subj, day, itime)] for cl in profs[prof]['classi'] for subj in profs[prof]['classi'][cl]]
                oras = model.NewBoolVar(f'var{runner2}')
                runner2 += 1
                model.AddBoolOr(haora).OnlyEnforceIf(oras)
                model.AddBoolAnd([j.Not() for j in haora]).OnlyEnforceIf(oras.Not())
                hasit.append(oras)
            #avoid prof with only 1 hour in any day
            model.Add(sum(hasit) != 1)
            buco2 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[0], hasit[1].Not(), hasit[2]]).OnlyEnforceIf(buco2)
            model.AddBoolOr([hasit[0].Not(), hasit[1], hasit[2].Not()]).OnlyEnforceIf(buco2.Not())

            buco3 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[1], hasit[2].Not(), hasit[3]]).OnlyEnforceIf(buco3)
            model.AddBoolOr([hasit[1].Not(), hasit[2], hasit[3].Not()]).OnlyEnforceIf(buco3.Not())

            buco4 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[2], hasit[3].Not(), hasit[4]]).OnlyEnforceIf(buco4)
            model.AddBoolOr([hasit[2].Not(), hasit[3], hasit[4].Not()]).OnlyEnforceIf(buco4.Not())

            buco23 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[0], hasit[1].Not(), hasit[2].Not(), hasit[3]]).OnlyEnforceIf(buco23)
            model.AddBoolOr([hasit[0].Not(), hasit[1], hasit[2], hasit[3].Not()]).OnlyEnforceIf(buco23.Not())

            buco34 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[1], hasit[2].Not(), hasit[3].Not(), hasit[4]]).OnlyEnforceIf(buco34)
            model.AddBoolOr([hasit[1].Not(), hasit[2], hasit[3], hasit[4].Not()]).OnlyEnforceIf(buco34.Not())

            buco234 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[0], hasit[1].Not(), hasit[2].Not(), hasit[3].Not(), hasit[4]]).OnlyEnforceIf(buco234)
            model.AddBoolOr([hasit[0].Not(), hasit[1], hasit[2], hasit[3], hasit[4].Not()]).OnlyEnforceIf(buco234.Not())

            cinqueore = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.Add(sum(hasit) > 4).OnlyEnforceIf(cinqueore)
            model.Add(sum(hasit) <= 4).OnlyEnforceIf(cinqueore.Not())

            accumbuchiprof += buco2 + buco3 + buco4 + 2 * buco23 + 2 * buco34 + 3 * buco234
            cinqueoreprof += cinqueore
        accumbuchi += accumbuchiprof
        cinqueoretot += cinqueoreprof
    return accumbuchi, cinqueoretot

for start in range(0, len(all_pairs), batch_size):

    print(f"Batch number: {batchn}")
    time.sleep(3)
    batchn+=1

    batch = all_pairs[start:start + batch_size]
    included_pairs.update(batch)

    model = cp_model.CpModel()

    lectures = add_lecture_variables(model, included_pairs, profs, rangedays, rangetimes)
    check_feasibility(model, "lecture variables")

    full_profs = set()
    for prof in profs:
        if all((prof, cl) in included_pairs for cl in profs[prof]['classi']):
            full_profs.add(prof)

    gliberi = add_gliberi_variables(model, full_profs, profs)
    check_feasibility(model, "gliberi variables")

    add_hour_constraints(model, lectures, included_pairs, profs, rangedays, rangetimes)
    check_feasibility(model, "hour constraints")

    full_classes = set()
    for cl in set(c for _, c in included_pairs):
        if all((prof, cl) in included_pairs for prof in class_profs[cl]):
            full_classes.add(cl)

    add_no_holes_constraints(model, lectures, full_classes, class_profs, profs, included_pairs, rangedays, rangetimes)
    check_feasibility(model, "no holes constraints")

    add_no_overlap_constraints(model, lectures, included_pairs, profs, class_profs, rangedays, rangetimes)
    check_feasibility(model, "no overlap constraints")

    accumprimmat = add_consecutive_constraints(model, lectures, classes, profs, included_pairs, rangedays, rangetimes)
    check_feasibility(model, "consecutive constraints")

    totpenaltore = add_uniform_class_penalties(model, lectures, classes, profs, included_pairs, rangedays, rangetimes)
    check_feasibility(model, "uniform class penalties")

    totpenaltoreprof = add_uniform_prof_penalties(model, lectures, full_profs, profs, rangedays, rangetimes)
    check_feasibility(model, "uniform prof penalties")

    add_max_hours_constraints(model, lectures, classes, profs, included_pairs, rangedays, rangetimes)
    check_feasibility(model, "max hours constraints")

    accumbuchi, cinqueoretot = add_buche_penalties(model, lectures, full_profs, profs, rangedays, rangetimes)
    check_feasibility(model, "buche penalties")

    add_free_days_constraints(model, lectures, full_profs, profs, gliberi, rangedays, rangetimes)
    check_feasibility(model, "free days constraints")

    # Objective
    tominimize = sum(gliberi[prof]['choice'][1] * 50 for prof in gliberi)+sum(gliberi[prof]['choice'][2] * 100 for prof in gliberi) + accumprimmat * 20 + accumbuchi * 30 + cinqueoretot * 40 + totpenaltore * 0.8 + totpenaltoreprof * 0.2
    model.Minimize(tominimize)

    # Hints
    for key, var in lectures.items():
        if key in current_hints:
            model.AddHint(var, current_hints[key])

    solver = cp_model.CpSolver()
    solver.parameters.log_search_progress = True
    solver.parameters.num_search_workers = 64
    solver.parameters.max_time_in_seconds = maxtimeinsec
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.UNKNOWN):
        for key, var in lectures.items():
            current_hints[key] = solver.Value(var)
    else:
        print(f"model INFEASIBLE at step {batchn}", batchn)
        exit()

# Final full optimization

def add_full_schedule_constraints(model, lectures, classes, class_profs, profs, rangedays, rangetimes):

    for cl in classes:
        continue
        sixth=[]
        for day in rangedays:

            for hour in rangetimes:
                accum = sum(lectures[(prof, cl, subj, day, hour)] for prof in class_profs[cl] for subj in profs[prof]['classi'][cl])
                if hour < 12:
                    model.Add(accum == 1)
                if hour == 12 and cl[0] == '5':
                    model.Add(accum == 1)
                if hour == 13:
                    sixth.append(accum)
        model.Add(sum(sixth)<=1)

def add_no_holes_final_constraints(model, lectures, classes, class_profs, profs, rangedays, rangetimes):
    for cl in classes:
        ###continue
        for day in rangedays:
            accums = []
            for hour in rangetimes:
                accum = sum(lectures[(prof, cl, subj, day, hour)] for prof in class_profs[cl] for subj in profs[prof]['classi'][cl])
                accums.append(accum)
            model.Add(accums[0] == 1)
            for i in range(len(accums) - 1):
                model.Add(accums[i + 1] <= accums[i])

def add_consecutive_final_constraints(model, lectures, classes, profs, rangedays, rangetimes):
    runner = 0
    accumprimmat = 0
    for cl in classes:
        ##continue
        accummat = []
        accumginn = []
        for prof in profs:
            if cl in profs[prof]['classi']:
                if 'Matematica' in profs[prof]['classi'][cl]:
                    for day in rangedays:
                        for itime in range(8, 12):
                            a = model.NewBoolVar(f'cons{runner}')
                            runner += 1
                            model.AddBoolAnd([lectures[(prof, cl, 'Matematica', day, itime)], lectures[(prof, cl, 'Matematica', day, itime + 1)]]).OnlyEnforceIf(a)
                            model.AddBoolOr([lectures[(prof, cl, 'Matematica', day, itime)].Not(), lectures[(prof, cl, 'Matematica', day, itime + 1)].Not()]).OnlyEnforceIf(a.Not())
                            accummat.append(a)
                        for itime in rangetimes:
                            accumprimmat += lectures[(prof, cl, 'Matematica', day, itime)] * (itime - 7)
                if 'Scienzemotorie' in profs[prof]['classi'][cl]:
                    for day in rangedays:
                        for itime in range(8, 12):
                            c = model.NewBoolVar(f'cons{runner}')
                            runner += 1
                            model.AddBoolAnd([lectures[(prof, cl, 'Scienzemotorie', day, itime)], lectures[(prof, cl, 'Scienzemotorie', day, itime + 1)]]).OnlyEnforceIf(c)
                            model.AddBoolOr([lectures[(prof, cl, 'Scienzemotorie', day, itime)].Not(), lectures[(prof, cl, 'Scienzemotorie', day, itime + 1)].Not()]).OnlyEnforceIf(c.Not())
                            accumginn.append(c)
        model.AddBoolOr(accummat)
        model.AddBoolOr(accumginn)
    return accumprimmat

def add_uniform_class_final_penalties(model, lectures, classes, profs, rangedays, rangetimes):
    totpenaltore = 0
    runner3 = 0
    for cl in classes:
        for prof in profs:
            if cl in profs[prof]['classi']:
                for subj in profs[prof]['classi'][cl]:
                    thisore = profs[prof]['classi'][cl][subj]['ore']
                    for day in rangedays:
                        howmany = [lectures[(prof, cl, subj, day, itime)] for itime in rangetimes]
                        iore = model.NewIntVar(-40, 40, f'varore{runner3}')
                        iore2 = model.NewIntVar(0, 1600, f'var2ore{runner3}')
                        runner3 += 1
                        model.Add(iore == sum(howmany) * 6 - thisore)
                        model.AddMultiplicationEquality(iore2, [iore, iore])
                        totpenaltore += iore2
    return totpenaltore

def add_uniform_prof_final_penalties(model, lectures, profs, rangedays, rangetimes):
    totpenaltoreprof = 0
    runner4 = 0
    for prof in profs:
        thisore = profs[prof]['tot_ore']
        for day in rangedays:
            howmany = [lectures[(prof, cl, subj, day, itime)] for cl in profs[prof]['classi'] for subj in profs[prof]['classi'][cl] for itime in rangetimes]
            ioreprof = model.NewIntVar(-40, 40, f'varoreprof{runner4}')
            iore2prof = model.NewIntVar(0, 1600, f'var2oreprof{runner4}')
            runner4 += 1
            model.Add(ioreprof == sum(howmany) * 6 - thisore)
            model.AddMultiplicationEquality(iore2prof, [ioreprof, ioreprof])
            totpenaltoreprof += iore2prof
    return totpenaltoreprof

def add_buche_final_penalties(model, lectures, profs, rangedays, rangetimes):
    accumbuchi = 0
    cinqueoretot = 0
    runner2 = 0
    for prof in profs:
        ##continue
        accumbuchiprof = 0
        cinqueoreprof = 0
        for day in rangedays:
            hasit = []
            for itime in rangetimes:
                haora = [lectures[(prof, cl, subj, day, itime)] for cl in profs[prof]['classi'] for subj in profs[prof]['classi'][cl]]
                oras = model.NewBoolVar(f'var{runner2}')
                runner2 += 1
                model.AddBoolOr(haora).OnlyEnforceIf(oras)
                model.AddBoolAnd([j.Not() for j in haora]).OnlyEnforceIf(oras.Not())
                hasit.append(oras)
            model.Add(sum(hasit) != 1)
            buco2 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[0], hasit[1].Not(), hasit[2]]).OnlyEnforceIf(buco2)
            model.AddBoolOr([hasit[0].Not(), hasit[1], hasit[2].Not()]).OnlyEnforceIf(buco2.Not())

            buco3 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[1], hasit[2].Not(), hasit[3]]).OnlyEnforceIf(buco3)
            model.AddBoolOr([hasit[1].Not(), hasit[2], hasit[3].Not()]).OnlyEnforceIf(buco3.Not())

            buco4 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[2], hasit[3].Not(), hasit[4]]).OnlyEnforceIf(buco4)
            model.AddBoolOr([hasit[2].Not(), hasit[3], hasit[4].Not()]).OnlyEnforceIf(buco4.Not())

            buco23 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[0], hasit[1].Not(), hasit[2].Not(), hasit[3]]).OnlyEnforceIf(buco23)
            model.AddBoolOr([hasit[0].Not(), hasit[1], hasit[2], hasit[3].Not()]).OnlyEnforceIf(buco23.Not())

            buco34 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[1], hasit[2].Not(), hasit[3].Not(), hasit[4]]).OnlyEnforceIf(buco34)
            model.AddBoolOr([hasit[1].Not(), hasit[2], hasit[3], hasit[4].Not()]).OnlyEnforceIf(buco34.Not())

            buco234 = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.AddBoolAnd([hasit[0], hasit[1].Not(), hasit[2].Not(), hasit[3].Not(), hasit[4]]).OnlyEnforceIf(buco234)
            model.AddBoolOr([hasit[0].Not(), hasit[1], hasit[2], hasit[3], hasit[4].Not()]).OnlyEnforceIf(buco234.Not())

            cinqueore = model.NewBoolVar(f'var{runner2}')
            runner2 += 1
            model.Add(sum(hasit) > 4).OnlyEnforceIf(cinqueore)
            model.Add(sum(hasit) <= 4).OnlyEnforceIf(cinqueore.Not())

            accumbuchiprof += buco2 + buco3 + buco4 + 2 * buco23 + 2 * buco34 + 3 * buco234
            cinqueoreprof += cinqueore
        accumbuchi += accumbuchiprof
        cinqueoretot += cinqueoreprof
        model.Add(accumbuchiprof <= 3)
        #model.Add(accumbuchiprof >= 1)
        model.Add(cinqueoreprof <= 2)
    return accumbuchi, cinqueoretot

def add_max_hours_final_constraints(model, lectures, classes, profs, rangedays, rangetimes):
    for cl in classes:
        for day in rangedays:
            for prof in profs:
                if cl in profs[prof]['classi']:
                    accum = []
                    for subj in profs[prof]['classi'][cl]:
                        temp = [lectures[(prof, cl, subj, day, itime)] for itime in rangetimes]
                        model.Add(sum(temp) <= 2)
                        accum.extend(temp)
                    model.Add(sum(accum) <= 3)

model = cp_model.CpModel()

lectures = {}
for prof in profs:
    for cl in profs[prof]['classi']:
        for subj in profs[prof]['classi'][cl]:
            for day in rangedays:
                for hour in rangetimes:
                    lectures[(prof, cl, subj, day, hour)] = model.NewBoolVar(f'prof{prof}_{cl}_{subj}_{day}_{hour}')
check_feasibility(model, "final lecture variables")

gliberi = {}
for prof in profs:
    gliberi[prof] = {'days': profs[prof]['glibero'], 'choice': [model.NewBoolVar(f'prof{prof}_first'), model.NewBoolVar(f'prof{prof}_second')]}
    model.AddBoolXOr(gliberi[prof]['choice'])
check_feasibility(model, "final gliberi variables")

# Hour constraints
for prof in profs:
    for cl in profs[prof]['classi']:
        for subj in profs[prof]['classi'][cl]:
            myhours = profs[prof]['classi'][cl][subj]['ore']
            model.Add(sum(lectures[(prof, cl, subj, day, hour)] for day in rangedays for hour in rangetimes) == myhours)
check_feasibility(model, "final hour constraints")

# No overlap
add_no_overlap_constraints(model, lectures, set((p, c) for p in profs for c in profs[p]['classi']), profs, class_profs, rangedays, rangetimes)
check_feasibility(model, "final no overlap constraints")

# Full schedule for classes
add_full_schedule_constraints(model, lectures, classes, class_profs, profs, rangedays, rangetimes)
check_feasibility(model, "final full schedule constraints")

# No holes for classes
add_no_holes_final_constraints(model, lectures, classes, class_profs, profs, rangedays, rangetimes)
check_feasibility(model, "final no holes constraints")

# Consecutive
accumprimmat = add_consecutive_final_constraints(model, lectures, classes, profs, rangedays, rangetimes)
check_feasibility(model, "final consecutive constraints")

# Uniform class
totpenaltore = add_uniform_class_final_penalties(model, lectures, classes, profs, rangedays, rangetimes)
check_feasibility(model, "final uniform class penalties")

# Uniform prof
totpenaltoreprof = add_uniform_prof_final_penalties(model, lectures, profs, rangedays, rangetimes)
check_feasibility(model, "final uniform prof penalties")

# Buche
accumbuchi, cinqueoretot = add_buche_final_penalties(model, lectures, profs, rangedays, rangetimes)
check_feasibility(model, "final buche penalties")

# Max hours same
add_max_hours_final_constraints(model, lectures, classes, profs, rangedays, rangetimes)
check_feasibility(model, "final max hours constraints")

# Free days
add_free_days_constraints(model, lectures, profs, profs, gliberi, rangedays, rangetimes)  # full_profs is all profs here
check_feasibility(model, "final free days constraints")

# Objective
tominimize = sum(gliberi[prof]['choice'][1] * 50 for prof in gliberi) + accumprimmat * 20 + accumbuchi * 30 + cinqueoretot * 40 + totpenaltore * 0.8 + totpenaltoreprof * 0.2
model.Minimize(tominimize)

# Hints
for key, var in lectures.items():
    if key in current_hints:
        model.AddHint(var, current_hints[key])

solver = cp_model.CpSolver()
solver.parameters.log_search_progress = True
solver.parameters.num_search_workers = 64
solver.parameters.max_time_in_seconds = maxtimeinsec
status = solver.Solve(model)
print(solver.ResponseStats())

for prof in profs:
    print(prof)
    print('**')
    for day in rangedays:
        print(day)
        for itime in rangetimes:
            for cl in profs[prof]['classi']:
                for subj in profs[prof]['classi'][cl]:
                    if solver.BooleanValue(lectures[(prof, cl, subj, day, itime)]):
                        print([itime, cl, subj])

for cl in classes:
    print(cl)
    for day in rangedays:
        print(day)
        for itime in rangetimes:
            for prof in profs:
                if cl in profs[prof]['classi']:
                    for subj in profs[prof]['classi'][cl]:
                        if solver.BooleanValue(lectures[(prof, cl, subj, day, itime)]):
                            print([itime, prof, subj])

solution = {}
if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    for key, var in lectures.items():
        solution[key] = solver.Value(var)
    with open('solution_timetable.pkl', 'wb') as file:
        pickle.dump(solution, file)
else:
    print("No solution found.")
