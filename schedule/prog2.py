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

maxtimeinsec=80
batch_size = 15

classes=['1A','1B','2A','2B','3A','3B','4A', '5A', '4B', '5B']

profs={}
profs['Picasso']={'classi':{'1A':{},'1B':{},'2A':{},'2B':{},'3A':{},'3B':{}, '4A':{}, '4B':{}, '5A':{}, '5B':{}},
                  'glibero':[4,3]
                 }
profs['Picasso']['classi']['1A']['arte']={'ore':2}
profs['Picasso']['classi']['1B']['arte']={'ore':2}
profs['Picasso']['classi']['2A']['arte']={'ore':2}
profs['Picasso']['classi']['2B']['arte']={'ore':2}
profs['Picasso']['classi']['3A']['arte']={'ore':2}
profs['Picasso']['classi']['3B']['arte']={'ore':2}
profs['Picasso']['classi']['4A']['arte']={'ore':2}
profs['Picasso']['classi']['4B']['arte']={'ore':2}
profs['Picasso']['classi']['5A']['arte']={'ore':1}
profs['Picasso']['classi']['5B']['arte']={'ore':1}

profs['MMeBovary']={'classi':{'1A':{},'1B':{},'4A':{},'2B':{},'3A':{},'3B':{}},
                  'glibero':[1,5]
                 }
profs['MMeBovary']['classi']['1A']['francese']={'ore':2}
profs['MMeBovary']['classi']['1B']['francese']={'ore':2}
profs['MMeBovary']['classi']['4A']['francese']={'ore':4}
profs['MMeBovary']['classi']['2B']['francese']={'ore':4}
profs['MMeBovary']['classi']['3A']['francese']={'ore':3}
profs['MMeBovary']['classi']['3B']['francese']={'ore':3}

profs['Macron']={'classi':{'2A':{},'4B':{},'5A':{},'5B':{}},
                  'glibero':[4,3]
                 }
profs['Macron']['classi']['2A']['francese']={'ore':4}
profs['Macron']['classi']['4B']['francese']={'ore':4}
profs['Macron']['classi']['5A']['francese']={'ore':5}
profs['Macron']['classi']['5B']['francese']={'ore':5}

profs['Stecca']={'classi':{'1A':{},'1B':{},'2A':{},'2B':{},'3A':{},'3B':{},'4A':{},'4B':{},'5A':{},'5B':{}},
                  'glibero':[2,5]
                 }
profs['Stecca']['classi']['1A']['ginnastica']={'ore':2}
profs['Stecca']['classi']['1B']['ginnastica']={'ore':2}
profs['Stecca']['classi']['2A']['ginnastica']={'ore':2}
profs['Stecca']['classi']['2B']['ginnastica']={'ore':2}
profs['Stecca']['classi']['3A']['ginnastica']={'ore':2}
profs['Stecca']['classi']['3B']['ginnastica']={'ore':2}
profs['Stecca']['classi']['4A']['ginnastica']={'ore':2}
profs['Stecca']['classi']['4B']['ginnastica']={'ore':2}
profs['Stecca']['classi']['5A']['ginnastica']={'ore':2}
profs['Stecca']['classi']['5B']['ginnastica']={'ore':2}

profs['DonMauro']={'classi':{'1A':{},'1B':{},'2A':{},'2B':{},'3A':{},'3B':{},'4A':{},'4B':{},'5A':{},'5B':{}},
                  'glibero':[1,2]
                 }
profs['DonMauro']['classi']['1A']['religione']={'ore':1}
profs['DonMauro']['classi']['1B']['religione']={'ore':1}
profs['DonMauro']['classi']['2A']['religione']={'ore':1}
profs['DonMauro']['classi']['2B']['religione']={'ore':1}
profs['DonMauro']['classi']['3A']['religione']={'ore':1}
profs['DonMauro']['classi']['3B']['religione']={'ore':1}
profs['DonMauro']['classi']['4A']['religione']={'ore':1}
profs['DonMauro']['classi']['4B']['religione']={'ore':1}
profs['DonMauro']['classi']['5A']['religione']={'ore':1}
profs['DonMauro']['classi']['5B']['religione']={'ore':1}

profs['GBorghi']={'classi':{'5A':{}, '1A':{},'3B':{},'1B':{}},
                  'glibero':[3,4]
                 }
profs['GBorghi']['classi']['1A']['matematica']={'ore':6}
profs['GBorghi']['classi']['1B']['fisica']={'ore':4}
profs['GBorghi']['classi']['5A']['matematica']={'ore':5}
profs['GBorghi']['classi']['3B']['fisica']={'ore':3}

profs['Einstein']={'classi':{'4A':{},'4B':{},'5A':{}},
                  'glibero':[6,4]
                 }
profs['Einstein']['classi']['4A']['matematica']={'ore':5}
profs['Einstein']['classi']['4A']['fisica']={'ore':4}
profs['Einstein']['classi']['5A']['fisica']={'ore':4}
profs['Einstein']['classi']['4B']['matematica']={'ore':5}

profs['Rubbia']={'classi':{'3B':{},'4B':{}, '5B':{}},
                  'glibero':[1,3]
                 }
profs['Rubbia']['classi']['4B']['fisica']={'ore':4}
profs['Rubbia']['classi']['3B']['matematica']={'ore':5}
profs['Rubbia']['classi']['5B']['matematica']={'ore':5}
profs['Rubbia']['classi']['5B']['fisica']={'ore':4}

profs['ESimoncelli']={'classi':{'1A':{},'2B':{},'3A':{}},
                      'glibero':[1,4]
                     }
profs['ESimoncelli']['classi']['1A']['fisica']={'ore':4}
profs['ESimoncelli']['classi']['2B']['matematica']={'ore':7}
profs['ESimoncelli']['classi']['2B']['fisica']={'ore':2}
profs['ESimoncelli']['classi']['3A']['matematica']={'ore':5}

profs['EMajni']={'classi':{'1B':{},'2A':{},'3A':{}},
                 'glibero':[3,4]
                }
profs['EMajni']['classi']['1B']['matematica']={'ore':6}
profs['EMajni']['classi']['2A']['matematica']={'ore':7}
profs['EMajni']['classi']['2A']['fisica']={'ore':2}
profs['EMajni']['classi']['3A']['fisica']={'ore':3}

profs['BMorandi']={'classi':{'2A':{},'2B':{},'3A':{},'3B':{}},
                   'glibero':[1,6]
                  }
profs['BMorandi']['classi']['2A']['inglese']={'ore':4}
profs['BMorandi']['classi']['2B']['inglese']={'ore':4}
profs['BMorandi']['classi']['3A']['inglese']={'ore':5}
profs['BMorandi']['classi']['3B']['inglese']={'ore':5}

profs['Shakespeare']={'classi':{'1A':{},'1B':{},'4A':{},'4B':{},'5A':{},'5B':{} },
                   'glibero':[4,6]
                  }
profs['Shakespeare']['classi']['1A']['inglese']={'ore':2}
profs['Shakespeare']['classi']['1B']['inglese']={'ore':2}
profs['Shakespeare']['classi']['4A']['inglese']={'ore':3}
profs['Shakespeare']['classi']['4B']['inglese']={'ore':3}
profs['Shakespeare']['classi']['5A']['inglese']={'ore':4}
profs['Shakespeare']['classi']['5B']['inglese']={'ore':4}

profs['AMorelli']={'classi':{'1A':{},'3A':{},'2B':{},'3B':{},'5B':{}},
                   'glibero':[3,6]
                  }
profs['AMorelli']['classi']['1A']['italiano']={'ore':4}
profs['AMorelli']['classi']['1A']['latino']={'ore':3}
profs['AMorelli']['classi']['5B']['latino']={'ore':3}
profs['AMorelli']['classi']['3A']['latino']={'ore':2}
profs['AMorelli']['classi']['2B']['italiano']={'ore':3}
profs['AMorelli']['classi']['3B']['italiano']={'ore':3}

profs['Gadda']={'classi':{'5A':{},'4A':{}, '4B':{}},
                   'glibero':[1,4]
                  }
profs['Gadda']['classi']['5A']['italiano']={'ore':5}
profs['Gadda']['classi']['5A']['latino']={'ore':3}
profs['Gadda']['classi']['4B']['latino']={'ore':3}
profs['Gadda']['classi']['4A']['italiano']={'ore':5}

profs['Ungaretti']={'classi':{'5B':{},'4B':{},'2A':{}, '4A':{}},
                   'glibero':[1,4]
                  }
profs['Ungaretti']['classi']['5B']['italiano']={'ore':5}
profs['Ungaretti']['classi']['2A']['latino']={'ore':3}
profs['Ungaretti']['classi']['4A']['latino']={'ore':3}
profs['Ungaretti']['classi']['4B']['italiano']={'ore':5}

profs['MLRosati']={'classi':{'1B':{},'2A':{},'3A':{},'2B':{},'3B':{}},
                   'glibero':[1,6]
                  }
profs['MLRosati']['classi']['1B']['italiano']={'ore':4}
profs['MLRosati']['classi']['1B']['latino']={'ore':3}
profs['MLRosati']['classi']['2B']['latino']={'ore':3}
profs['MLRosati']['classi']['3B']['latino']={'ore':2}
profs['MLRosati']['classi']['2A']['italiano']={'ore':3}
profs['MLRosati']['classi']['3A']['italiano']={'ore':3}

# Compute total hours for each prof
for prof in profs:
    profs[prof]['tot_ore'] = sum(profs[prof]['classi'][cl][subj]['ore'] for cl in profs[prof]['classi'] for subj in profs[prof]['classi'][cl])

materiemax={'inglese':2, 'matematica':2, 'fisica':2, 'italiano':2, 'latino':2}

rangedays=range(1,7)
rangetimes=range(8,13)

# All prof-class pairs
all_pairs = [(prof, cl) for prof in profs for cl in profs[prof]['classi']]
random.shuffle(all_pairs)

# Class to profs mapping
class_profs = {cl: set() for cl in classes}
for prof in profs:
    for cl in profs[prof]['classi']:
        class_profs[cl].add(prof)

current_hints = {}
included_pairs = set()

for start in range(0, len(all_pairs), batch_size):
    batch = all_pairs[start:start + batch_size]
    included_pairs.update(batch)

    model = cp_model.CpModel()

    lectures = {}
    gliberi = {}

    # Create variables for included pairs
    for prof, cl in included_pairs:
        for subj in profs[prof]['classi'][cl]:
            for day in rangedays:
                for hour in rangetimes:
                    lectures[(prof, cl, subj, day, hour)] = model.NewBoolVar(f'prof{prof}_{cl}_{subj}_{day}_{hour}')

    # Identify fully included profs
    full_profs = set()
    for prof in profs:
        if all((prof, cl) in included_pairs for cl in profs[prof]['classi']):
            full_profs.add(prof)
            gliberi[prof] = {'days': profs[prof]['glibero'], 'choice': [model.NewBoolVar(f'prof{prof}_first'), model.NewBoolVar(f'prof{prof}_second')]}
            model.AddBoolXOr(gliberi[prof]['choice'])

    # Hour constraints
    for prof, cl in included_pairs:
        for subj in profs[prof]['classi'][cl]:
            myhours = profs[prof]['classi'][cl][subj]['ore']
            model.Add(sum(lectures[(prof, cl, subj, day, hour)] for day in rangedays for hour in rangetimes) == myhours)

    # Free days for full profs
    for prof in full_profs:
        for cl in profs[prof]['classi']:
            for subj in profs[prof]['classi'][cl]:
                for day in rangedays:
                    sum_day = sum(lectures[(prof, cl, subj, day, hour)] for hour in rangetimes)
                    if day == gliberi[prof]['days'][0]:
                        model.Add(sum_day == 0).OnlyEnforceIf(gliberi[prof]['choice'][0])
                    elif day == gliberi[prof]['days'][1]:
                        model.Add(sum_day == 0).OnlyEnforceIf(gliberi[prof]['choice'][1])

    # No overlap prof or class
    for day in rangedays:
        for hour in rangetimes:
            # Prof overlap
            for prof in set(p for p, _ in included_pairs):
                accum = sum(lectures[(prof, cl, subj, day, hour)] for cl in profs[prof]['classi'] if (prof, cl) in included_pairs for subj in profs[prof]['classi'][cl])
                model.Add(accum <= 1)
            # Class overlap
            for cl in set(c for _, c in included_pairs):
                accum = sum(lectures[(prof, cl, subj, day, hour)] for prof in class_profs[cl] if (prof, cl) in included_pairs for subj in profs[prof]['classi'][cl])
                model.Add(accum <= 1)

    # Consecutive
    runner = 0
    accumprimmat = 0
    for cl in classes:
        accummat = []
        accumginn = []
        # accumeng = []  # Not used in original
        mat_included = any(cl in profs[prof]['classi'] and 'matematica' in profs[prof]['classi'][cl] and (prof, cl) in included_pairs for prof in profs)
        ginn_included = any(cl in profs[prof]['classi'] and 'ginnastica' in profs[prof]['classi'][cl] and (prof, cl) in included_pairs for prof in profs)
        # eng_included = ... if needed
        for prof in profs:
            if cl in profs[prof]['classi'] and (prof, cl) in included_pairs:
                if 'matematica' in profs[prof]['classi'][cl]:
                    for day in rangedays:
                        for time in range(8, 12):
                            a = model.NewBoolVar(f'cons{runner}')
                            runner += 1
                            model.AddBoolAnd([lectures[(prof, cl, 'matematica', day, time)], lectures[(prof, cl, 'matematica', day, time + 1)]]).OnlyEnforceIf(a)
                            model.AddBoolOr([lectures[(prof, cl, 'matematica', day, time)].Not(), lectures[(prof, cl, 'matematica', day, time + 1)].Not()]).OnlyEnforceIf(a.Not())
                            accummat.append(a)
                        for time in rangetimes:
                            accumprimmat += lectures[(prof, cl, 'matematica', day, time)] * (time - 7)
                if 'ginnastica' in profs[prof]['classi'][cl]:
                    for day in rangedays:
                        for time in range(8, 12):
                            c = model.NewBoolVar(f'cons{runner}')
                            runner += 1
                            model.AddBoolAnd([lectures[(prof, cl, 'ginnastica', day, time)], lectures[(prof, cl, 'ginnastica', day, time + 1)]]).OnlyEnforceIf(c)
                            model.AddBoolOr([lectures[(prof, cl, 'ginnastica', day, time)].Not(), lectures[(prof, cl, 'ginnastica', day, time + 1)].Not()]).OnlyEnforceIf(c.Not())
                            accumginn.append(c)
        if mat_included:
            model.AddBoolOr(accummat)
        if ginn_included:
            model.AddBoolOr(accumginn)
        # if eng_included: model.AddBoolAnd(accumeng)

    # Uniform class
    totpenaltore = 0
    runner3 = 0
    for cl in classes:
        for prof in profs:
            if cl in profs[prof]['classi'] and (prof, cl) in included_pairs:
                for subj in profs[prof]['classi'][cl]:
                    thisore = profs[prof]['classi'][cl][subj]['ore']
                    for day in rangedays:
                        howmany = [lectures[(prof, cl, subj, day, time)] for time in rangetimes]
                        iore = model.NewIntVar(-40, 40, f'varore{runner3}')
                        iore2 = model.NewIntVar(0, 1600, f'var2ore{runner3}')
                        runner3 += 1
                        model.Add(iore == sum(howmany) * 6 - thisore)
                        model.AddMultiplicationEquality(iore2, [iore, iore])
                        totpenaltore += iore2

    # Uniform prof for full profs
    totpenaltoreprof = 0
    runner4 = 0
    for prof in full_profs:
        thisore = profs[prof]['tot_ore']
        for day in rangedays:
            howmany = [lectures[(prof, cl, subj, day, time)] for cl in profs[prof]['classi'] for subj in profs[prof]['classi'][cl] for time in rangetimes]
            ioreprof = model.NewIntVar(-40, 40, f'varoreprof{runner4}')
            iore2prof = model.NewIntVar(0, 1600, f'var2oreprof{runner4}')
            runner4 += 1
            model.Add(ioreprof == sum(howmany) * 6 - thisore)
            model.AddMultiplicationEquality(iore2prof, [ioreprof, ioreprof])
            totpenaltoreprof += iore2prof

    # Max hours same subj/prof
    for cl in classes:
        for day in rangedays:
            for prof in profs:
                if cl in profs[prof]['classi'] and (prof, cl) in included_pairs:
                    accum = []
                    for subj in profs[prof]['classi'][cl]:
                        temp = [lectures[(prof, cl, subj, day, time)] for time in rangetimes]
                        model.Add(sum(temp) <= 2)
                        accum.extend(temp)
                    model.Add(sum(accum) <= 3)

    # Buche for full profs
    accumbuchi = 0
    cinqueoretot = 0
    runner2 = 0
    for prof in full_profs:
        accumbuchiprof = 0
        cinqueoreprof = 0
        for day in rangedays:
            hasit = []
            for time in rangetimes:
                haora = [lectures[(prof, cl, subj, day, time)] for cl in profs[prof]['classi'] for subj in profs[prof]['classi'][cl]]
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

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for key, var in lectures.items():
            current_hints[key] = solver.Value(var)

# Final full optimization
model = cp_model.CpModel()

lectures = {}
gliberi = {}

for prof in profs:
    for cl in profs[prof]['classi']:
        for subj in profs[prof]['classi'][cl]:
            for day in rangedays:
                for hour in rangetimes:
                    lectures[(prof, cl, subj, day, hour)] = model.NewBoolVar(f'prof{prof}_{cl}_{subj}_{day}_{hour}')

for prof in profs:
    gliberi[prof] = {'days': profs[prof]['glibero'], 'choice': [model.NewBoolVar(f'prof{prof}_first'), model.NewBoolVar(f'prof{prof}_second')]}
    model.AddBoolXOr(gliberi[prof]['choice'])

# Hour constraints
for prof in profs:
    for cl in profs[prof]['classi']:
        for subj in profs[prof]['classi'][cl]:
            myhours = profs[prof]['classi'][cl][subj]['ore']
            model.Add(sum(lectures[(prof, cl, subj, day, hour)] for day in rangedays for hour in rangetimes) == myhours)

# Free days
for prof in profs:
    for cl in profs[prof]['classi']:
        for subj in profs[prof]['classi'][cl]:
            for day in rangedays:
                sum_day = sum(lectures[(prof, cl, subj, day, hour)] for hour in rangetimes)
                if day == gliberi[prof]['days'][0]:
                    model.Add(sum_day == 0).OnlyEnforceIf(gliberi[prof]['choice'][0])
                elif day == gliberi[prof]['days'][1]:
                    model.Add(sum_day == 0).OnlyEnforceIf(gliberi[prof]['choice'][1])

# No overlap
for day in rangedays:
    for hour in rangetimes:
        for prof in profs:
            accum = sum(lectures[(prof, cl, subj, day, hour)] for cl in profs[prof]['classi'] for subj in profs[prof]['classi'][cl])
            model.Add(accum <= 1)
        for cl in classes:
            accum = sum(lectures[(prof, cl, subj, day, hour)] for prof in class_profs[cl] for subj in profs[prof]['classi'][cl])
            model.Add(accum <= 1)

# Full schedule for classes
for day in rangedays:
    for cl in classes:
        for hour in rangetimes:
            accum = sum(lectures[(prof, cl, subj, day, hour)] for prof in class_profs[cl] for subj in profs[prof]['classi'][cl])
            if hour < 12:
                model.Add(accum == 1)
            if hour >= 12 and cl[0] == '5':
                model.Add(accum == 1)

# Consecutive
runner = 0
accumprimmat = 0
for cl in classes:
    accummat = []
    accumginn = []
    for prof in profs:
        if cl in profs[prof]['classi']:
            if 'matematica' in profs[prof]['classi'][cl]:
                for day in rangedays:
                    for time in range(8, 12):
                        a = model.NewBoolVar(f'cons{runner}')
                        runner += 1
                        model.AddBoolAnd([lectures[(prof, cl, 'matematica', day, time)], lectures[(prof, cl, 'matematica', day, time + 1)]]).OnlyEnforceIf(a)
                        model.AddBoolOr([lectures[(prof, cl, 'matematica', day, time)].Not(), lectures[(prof, cl, 'matematica', day, time + 1)].Not()]).OnlyEnforceIf(a.Not())
                        accummat.append(a)
                    for time in rangetimes:
                        accumprimmat += lectures[(prof, cl, 'matematica', day, time)] * (time - 7)
            if 'ginnastica' in profs[prof]['classi'][cl]:
                for day in rangedays:
                    for time in range(8, 12):
                        c = model.NewBoolVar(f'cons{runner}')
                        runner += 1
                        model.AddBoolAnd([lectures[(prof, cl, 'ginnastica', day, time)], lectures[(prof, cl, 'ginnastica', day, time + 1)]]).OnlyEnforceIf(c)
                        model.AddBoolOr([lectures[(prof, cl, 'ginnastica', day, time)].Not(), lectures[(prof, cl, 'ginnastica', day, time + 1)].Not()]).OnlyEnforceIf(c.Not())
                        accumginn.append(c)
    model.AddBoolOr(accummat)
    model.AddBoolOr(accumginn)

# Uniform class
totpenaltore = 0
runner3 = 0
for cl in classes:
    for prof in profs:
        if cl in profs[prof]['classi']:
            for subj in profs[prof]['classi'][cl]:
                thisore = profs[prof]['classi'][cl][subj]['ore']
                for day in rangedays:
                    howmany = [lectures[(prof, cl, subj, day, time)] for time in rangetimes]
                    iore = model.NewIntVar(-40, 40, f'varore{runner3}')
                    iore2 = model.NewIntVar(0, 1600, f'var2ore{runner3}')
                    runner3 += 1
                    model.Add(iore == sum(howmany) * 6 - thisore)
                    model.AddMultiplicationEquality(iore2, [iore, iore])
                    totpenaltore += iore2

# Uniform prof
totpenaltoreprof = 0
runner4 = 0
for prof in profs:
    thisore = profs[prof]['tot_ore']
    for day in rangedays:
        howmany = [lectures[(prof, cl, subj, day, time)] for cl in profs[prof]['classi'] for subj in profs[prof]['classi'][cl] for time in rangetimes]
        ioreprof = model.NewIntVar(-40, 40, f'varoreprof{runner4}')
        iore2prof = model.NewIntVar(0, 1600, f'var2oreprof{runner4}')
        runner4 += 1
        model.Add(ioreprof == sum(howmany) * 6 - thisore)
        model.AddMultiplicationEquality(iore2prof, [ioreprof, ioreprof])
        totpenaltoreprof += iore2prof

# Buche
accumbuchi = 0
cinqueoretot = 0
runner2 = 0
for prof in profs:
    accumbuchiprof = 0
    cinqueoreprof = 0
    for day in rangedays:
        hasit = []
        for time in rangetimes:
            haora = [lectures[(prof, cl, subj, day, time)] for cl in profs[prof]['classi'] for subj in profs[prof]['classi'][cl]]
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
    model.Add(accumbuchiprof >= 1)
    model.Add(cinqueoreprof < 2)

# Max hours same
for cl in classes:
    for day in rangedays:
        for prof in profs:
            if cl in profs[prof]['classi']:
                accum = []
                for subj in profs[prof]['classi'][cl]:
                    temp = [lectures[(prof, cl, subj, day, time)] for time in rangetimes]
                    model.Add(sum(temp) <= 2)
                    accum.extend(temp)
                model.Add(sum(accum) <= 3)

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
        for time in rangetimes:
            for cl in profs[prof]['classi']:
                for subj in profs[prof]['classi'][cl]:
                    if solver.BooleanValue(lectures[(prof, cl, subj, day, time)]):
                        print([time, cl, subj])

for cl in classes:
    print(cl)
    for day in rangedays:
        print(day)
        for time in rangetimes:
            for prof in profs:
                if cl in profs[prof]['classi']:
                    for subj in profs[prof]['classi'][cl]:
                        if solver.BooleanValue(lectures[(prof, cl, subj, day, time)]):
                            print([time, prof, subj])

solution = {}
if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    for key, var in lectures.items():
        solution[key] = solver.Value(var)
    with open('solutionmock.pkl', 'wb') as file:
        pickle.dump(solution, file)
else:
    print("No solution found.")
