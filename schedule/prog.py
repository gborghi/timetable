import numpy as np
import pandas as pd
import time
import matplotlib.pyplot as plt
import pprint
from collections import Counter
from IPython.display import Image
from IPython.core.display import HTML

from ortools.sat.python import cp_model
model = cp_model.CpModel()
profs=['MMeBovary','DonMauro','GBorghi', 'ESimoncelli', 'Emajni', 'BMorandi','AMorelli','MLRosati', 'Stecca', 'Picasso', 'Einstein', 'Ungaretti', 'Rubbia', 'Gadda', 'Shakespeare', 'Macron']
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

lectures={}
gliberi={}
materiemax={'inglese':2, 'matematica':2, 'fisica':2, 'italiano':2, 'latino':2}

rangedays=range(1,7)
rangetimes=range(8,13)

for prof in profs.keys():
    myprof=prof
    profs[myprof]['tot_ore']=0
    gliberi[myprof]={'days':profs[prof]['glibero'], 'choice':[model.NewBoolVar('prof%s_first' % prof),model.NewBoolVar('prof%s_second' % prof)]}
    model.AddBoolXOr(gliberi[myprof]['choice'])
    for classe in profs[prof]['classi'].keys():
        myclass=classe
        for materia in profs[prof]['classi'][classe].keys():
            mymat=materia
            myhours=profs[prof]['classi'][classe][materia]['ore']
            for day in rangedays:
                myday=day
                for hour in rangetimes:
                    myhour=hour
                    lectures[(myprof,myclass,mymat,myday,myhour)]=model.NewBoolVar('prof%s_%s_%s_%i_%i' % (myprof,myclass,mymat,myday,myhour))
                #rispetta almeno uno dei due giorni liberi richiesti
                if(myday==gliberi[myprof]['days'][0]):
                    #pass
                    model.Add(sum(lectures[(myprof,myclass,mymat,myday,ihour)] for ihour in rangetimes)==0).OnlyEnforceIf(gliberi[myprof]['choice'][0])
                elif(myday==gliberi[myprof]['days'][1]):
                    #pass
                    model.Add(sum(lectures[(myprof,myclass,mymat,myday,ihour)] for ihour in rangetimes)==0).OnlyEnforceIf(gliberi[myprof]['choice'][1])
            #deve tornare il conto delle ore per prof per materia per classe
            profs[myprof]['tot_ore']+=myhours
            model.Add(sum(lectures[(myprof,myclass,mymat,iday,ihour)] for iday in rangedays for ihour in rangetimes) == myhours)

accumbuchi=0
cinqueoretot=0
runner2=0
for prof in profs.keys():
    accumbuchiprof=0
    cinqueoreprof=0
    for day in rangedays:
        hasit=[]
        for time in rangetimes:
            haora=[]
            for classe in profs[prof]['classi'].keys():
                for materia in profs[prof]['classi'][classe].keys():
                    temp1=lectures[(prof,classe,materia,day,time)]
                    haora.append(temp1)
            oras=model.NewBoolVar('var%i' % runner2)
            runner2+=1
            model.AddBoolOr(haora).OnlyEnforceIf(oras)
            model.AddBoolAnd(j.Not() for j in haora).OnlyEnforceIf(oras.Not())
            hasit.append(oras)
        #orre buche singole
        buco2=model.NewBoolVar('var%i' % runner2)
        runner2+=1
        model.AddBoolAnd([hasit[0], hasit[1].Not(), hasit[2]]).OnlyEnforceIf(buco2)
        model.AddBoolOr([hasit[0].Not(), hasit[1], hasit[2].Not()]).OnlyEnforceIf(buco2.Not())

        buco3=model.NewBoolVar('var%i' % runner2)
        runner2+=1
        model.AddBoolAnd([hasit[1], hasit[2].Not(), hasit[3]]).OnlyEnforceIf(buco3)
        model.AddBoolOr([hasit[1].Not(), hasit[2], hasit[3].Not()]).OnlyEnforceIf(buco3.Not())

        buco4=model.NewBoolVar('var%i' % runner2)
        runner2+=1
        model.AddBoolAnd([hasit[2], hasit[3].Not(), hasit[4]]).OnlyEnforceIf(buco4)
        model.AddBoolOr([hasit[2].Not(), hasit[3], hasit[4].Not()]).OnlyEnforceIf(buco4.Not())
        #ore buche doppie
        buco23=model.NewBoolVar('var%i' % runner2)
        runner2+=1
        model.AddBoolAnd([hasit[0], hasit[1].Not(), hasit[2].Not(), hasit[3]]).OnlyEnforceIf(buco23)
        model.AddBoolOr([hasit[0].Not(), hasit[1], hasit[2], hasit[3].Not()]).OnlyEnforceIf(buco23.Not())

        buco34=model.NewBoolVar('var%i' % runner2)
        runner2+=1
        model.AddBoolAnd([hasit[1], hasit[2].Not(), hasit[3].Not(), hasit[4]]).OnlyEnforceIf(buco34)
        model.AddBoolOr([hasit[1].Not(), hasit[2], hasit[3], hasit[4].Not()]).OnlyEnforceIf(buco34.Not())
        #ore buche triple
        buco234=model.NewBoolVar('var%i' % runner2)
        runner2+=1
        model.AddBoolAnd([hasit[0], hasit[1].Not(), hasit[2].Not(), hasit[3].Not(),hasit[4]]).OnlyEnforceIf(buco234)
        model.AddBoolOr([hasit[0].Not(), hasit[1], hasit[2], hasit[3], hasit[4].Not()]).OnlyEnforceIf(buco234.Not())
        #mai un'ora sola in un giorno nell'orario di un prof
        model.Add(sum(hasit)!=1)
        cinqueore=model.NewBoolVar('var%i' % runner2)
        runner2+=1
        model.Add(sum(hasit)>4).OnlyEnforceIf(cinqueore)
        model.Add(sum(hasit)<=4).OnlyEnforceIf(cinqueore.Not())

        accumbuchiprof+=buco2+buco3+buco4+2*buco23+2*buco34+3*buco234
        cinqueoreprof+=cinqueore

    accumbuchi+=accumbuchiprof
    cinqueoretot+=cinqueoreprof
    model.Add(accumbuchiprof<=3)
    model.Add(accumbuchiprof>=1)
    model.Add(cinqueoreprof<2)
for day in rangedays:
    for hour in rangetimes:
        for prof in profs.keys():
            #pass
            model.Add(sum(lectures[(prof,iclass,imat,day,hour)] for iclass in profs[prof]['classi'].keys() for imat in profs[prof]['classi'][iclass].keys() )<=1)
            #ogni prof ha al massimo una classe alla volta

        for classe in classes:
            accum=[]
            for prof in profs.keys():
                if classe in profs[prof]['classi'].keys():
                    #pass
                    accum.extend(lectures[(prof,classe,imat,day,hour)] for imat in profs[prof]['classi'][classe].keys())
            model.Add(sum(accum)<=1) #al massimo un prof e una materia alla volta per classe per ora

            #per compattare le ore delle classi ed evitare che entrino dopo le 8 o abbiano ore buche
            if hour<12:
                #pass
                model.Add(sum(accum)==1) #tutte le classi fanno lezione fino alle 12 almeno
            if hour>=12 and classe[0]=='5':
                model.Add(sum(accum)==1) #le quinte hanno orario pieno

#almeno una coppia di ore attaccate di matematica per ogni classe
runner=0
accumprimmat=0
for classe in classes:
    accummat=[]
    accumpore=[]
    accumeng=[]
    accumginn=[]
    for prof in profs.keys():
        if classe in profs[prof]['classi'].keys():
            if 'matematica' in profs[prof]['classi'][classe].keys():
                for day in rangedays:
                    for time in rangetimes[0:-1]:
                        a=model.NewBoolVar('cons%i' % runner)
                        runner+=1
                        model.AddBoolAnd([lectures[(prof,classe,'matematica',day,time)],lectures[(prof,classe,'matematica',day,time+1)]]).OnlyEnforceIf(a)
                        accummat.append(a)
                        accumprimmat+=lectures[(prof,classe,'matematica',day,time)]*time #math mostly on first hours
                    accumprimmat+=lectures[(prof,classe,'matematica',day,time)]*rangetimes[-1]
            if 'ginnastica' in profs[prof]['classi'][classe].keys():
                for day in rangedays:
                    for time in rangetimes[0:-1]:
                        c=model.NewBoolVar('cons%i' % runner)
                        model.AddBoolAnd([lectures[(prof,classe,'ginnastica',day,time)],lectures[(prof,classe,'ginnastica',day,time+1)]]).OnlyEnforceIf(c)
                        accumginn.append(c) #always two hours of ginnastica at a time
    model.AddBoolOr(accummat)
    model.AddBoolOr(accumginn)
    model.AddBoolAnd(accumeng)

totpenaltore=0
runner3=0
for classe in classes:
    for prof in profs.keys():
        if classe in profs[prof]['classi'].keys():
            for materia in profs[prof]['classi'][classe].keys():
                penaltore=0
                thisoreavg=profs[prof]['classi'][classe][materia]['ore'] #media ore/giorno di una certa materia (moltiplicato per 5)
                for day in rangedays:
                    howmany=[]
                    for time in rangetimes:
                        howmany.append(lectures[(prof,classe,materia, day, time)])
                    iore=model.NewIntVar(-40,40,'varore%i' % runner3)
                    #runner3+=1
                    iore2=model.NewIntVar(0,1600,'var2ore%i' % runner3)
                    runner3+=1
                    model.Add(iore==sum(howmany)*5-thisoreavg)
                    model.AddMultiplicationEquality(iore2,[iore,iore])
                    penaltore+=iore2 #uniform distribution of subjects in class timetable
                totpenaltore+=penaltore

totpenaltoreprof=0
runner4=0
for prof in profs.keys():
    thisoreavg=profs[prof]['tot_ore']
    for day in rangedays:
        howmany=[]
        for time in rangetimes:
            for classe in profs[prof]['classi'].keys():
                for materia in profs[prof]['classi'][classe].keys():
                 #media ore/giorno di una certa materia (moltiplicato per 5)
                    howmany.append(lectures[(prof,classe,materia, day,time)])
        ioreprof=model.NewIntVar(-40,40,'varoreprof%i' % runner4)
        #runner3+=1
        iore2prof=model.NewIntVar(0,1600,'var2oreprof%i' % runner4)
        runner4+=1
        model.Add(ioreprof==sum(howmany)*5-thisoreavg)
        model.AddMultiplicationEquality(iore2prof,[ioreprof,ioreprof])
        totpenaltoreprof+=iore2prof #uniform distribution of hours in prof timetable

for classe in classes:
    for day in rangedays:
        for prof in profs.keys():
            if classe in profs[prof]['classi'].keys():
                accum=[]
                for materia in profs[prof]['classi'][classe].keys():
                    temp=[lectures[(prof,classe,materia,day,time)] for time in rangetimes]
                    model.Add(sum(temp)<=2)
                    accum.extend(temp) #max 2 hours per day of same subject
                model.Add(sum(accum)<=3) #max 3 hours per day with same prof

tominimize=0
tominimize+=sum(gliberi[prof]['choice'][1]*50 for prof in profs.keys()) #cerca di dare ad ogni prof la prima scelta di giorno libero
tominimize+=accumprimmat*20 #preferably math on first hours
tominimize+=accumbuchi*30 #as few holes as possible
tominimize+=cinqueoretot*40 #as few full days as possible
tominimize+=totpenaltore*0.8+totpenaltoreprof*0.2 #mostly distributed schedule, both for profs and for students
model.Minimize(tominimize)

import json, pickle
if(True):
    with open('solution.pkl', 'rb') as file:
        ls = pickle.load(file)

    for key, value in ls.items():
        print([key, value])
        model.AddHint(lectures[key], value)

solver = cp_model.CpSolver()
solver.parameters.log_search_progress = True
solver.parameters.num_search_workers = 64
#solver.parameters.solution_limit = 10
#solver.parameters.max_time_in_seconds = 120.0
#solver.parameters.max_branches = 1000  # Example: Limit the search to 1000 branches
#solver.parameters.max_search_nodes = 1000  # Example: Limit to 1000 search nodes


status = solver.Solve(model)
print(solver.ResponseStats())

for prof in profs.keys():
    print(prof)
    print('**')
    for day in rangedays:
        print(day)
        for time in rangetimes:
            for classe in profs[prof]['classi'].keys():
                for materia in profs[prof]['classi'][classe].keys():
                    if solver.BooleanValue(lectures[(prof,classe,materia,day,time)]):
                        print([time,classe, materia])

for classe in classes:
    print(classe)
    for day in rangedays:
        print(day)
        for time in rangetimes:
            for prof in profs.keys():
                if(classe in profs[prof]['classi'].keys()):
                    for materia in profs[prof]['classi'][classe].keys():
                        if solver.BooleanValue(lectures[(prof,classe,materia,day,time)]):
                            print([time,prof, materia])


solution = {}
if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    for key, var in lectures.items():
        solution[key] = solver.Value(var)
    with open('solutionmock.pkl', 'wb') as file:
        pickle.dump(solution, file)
else:
    print("No solution found.")
