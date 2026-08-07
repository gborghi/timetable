# school_scheduler.py
import random
from math import ceil, floor
import copy
from faker import Faker
import numpy as np
from ortools.sat.python import cp_model
model = cp_model.CpModel()

fake = Faker()
Faker.seed(4321)
random.seed(10)
maxtime=60
# Probability weights for each day (Monday to Saturday)
day_weights = {
    'Monday': 15,
    'Tuesday': 5,
    'Wednesday': 15,
    'Thursday': 15,
    'Friday': 10,
    'Saturday': 16
}

curriculum_scores={
    'Scientifico':3,
    'ScienzeApplicate':1,
    'ScienzeUmane':-1,
    'EconomicoSociale_FRA':-2,
    'EconomicoSociale_SPA':-3,
    'EconomicoSociale_TED':-1,
    'Linguistico_FRA_SPA':0,
    'Linguistico_FRA_TED':1
}

class Teacher:
    def __init__(self, name, subject_group, max_hours, free_day, weights=None, birth=""):
        self.name = name
        self.subject_group = subject_group  # Instance of SubjectGroup
        self.subjects=subject_group.subjects
        self.max_hours = max_hours
        self.free_day = free_day
        self.assigned_hours = 0
        self.birth=birth
        self.totclasses=0
        self.totscore=0
        self.actual_hours=0
        self.totcurricula=0
        # Use provided weights if available; otherwise, use the subject group's default weights
        self.weights = weights if weights else subject_group.weights
        self.cattedra={}

class Subject:
    #for the class
    def __init__(self, name, weekly_hours):
        self.name = name
        self.weekly_hours = weekly_hours

class SubjectGroup:
    def __init__(self, name, subjects, weights=None):
        self.name=name
        self.subjects = subjects  # List of subject names
        # Initialize default weights for each subject
        if weights:
            self.weights = {subject: weight for subject, weight in weights.items()}
        else:
            self.weights = {subject: 1 for subject in subjects}

class SchoolClass:
    def __init__(self, section, year, curriculum):
        self.section = section
        self.year = year
        self.curriculum = curriculum.name
        self.subjects = curriculum.plan[year]  # key: subject name, value: weekly hours
        self.name=str(self.year)+str(self.section)+'_'+self.curriculum
        self.docenti={}
    def __str__(self):
        return str(self.year)+str(self.section)+'_'+self.curriculum


class Curriculum:
    def __init__(self, name, curriculum_subject_hours):
        self.name=name
        self.plan={}
        for j,k in curriculum_subject_hours.items():
            if j[0]==name:
                self.plan[j[1]]=k

def generate_subject_groups():
    groups=[]
    subject_group_dict={'A027': {'Matematica':20, 'Fisica':20},
                    'A011': {'Italiano':3, 'Latino':1, 'Geostoria':1},
                    'A017': {'Arte':1, 'DisegnoArte':1},
                    'A018': {'Scienzeumane':1},
                    'A019': {'Storia':1, 'Filosofia':1},
                    'A020': {'Fisica':1},
                    'A026': {'Matematica':1},
                    'A041': {'Informatica':1},
                    'A046': {'DirittoEconomia':1},
                    'A048': {'Scienzemotorie':1},
                    'A050': {'Scienzenaturali':1},
                    'A054': {'Arte':2},
                    'AA24': {'LinguaFrancese':10, 'ConversazioneFrancese':1},
                    'AB24': {'LinguaInglese':10, 'ConversazioneInglese':1},
                    'AC24': {'LinguaSpagnola':10, 'ConversazioneSpagnolo':1},
                    'AD24': {'LinguaTedesca':10, 'ConversazioneTedesco':1},
                    'BB02': {'ConversazioneInglese':10},
                    'BC02': {'ConversazioneSpagnolo':10},
                    'ADSS': {'Sostegno':1},
                    'IRC' : {'Religione':1}
                    }
    subjects_dict_groups={}
    for name, diction in subject_group_dict.items():
        #print(diction)
        groups.append(SubjectGroup(name, diction.keys(), weights=diction))
        for subject, weight in diction.items():
            #if subject in subjects_dict_groups:
            subjects_dict_groups.setdefault(subject,{name:weight})
            subjects_dict_groups[subject][name]=weight


    return subject_group_dict, groups, subjects_dict_groups

def generate_curriculum_subjects():
    curriculum_subject_hours = {
        ('Scientifico', 1): {'Matematica': 5, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':3, 'ConversazioneInglese':1, 'Latino':3, 'Italiano':4, 'Fisica':2, 'DisegnoArte':2, 'Scienzemotorie':2, 'Religione':1},
        ('Scientifico', 2): {'Matematica': 5, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':3, 'ConversazioneInglese':1, 'Latino':3, 'Italiano':4, 'Fisica':2, 'DisegnoArte':2, 'Scienzemotorie':2, 'Religione':1},
        ('Scientifico', 3): {'Matematica': 4, 'Scienzenaturali': 3, 'Storia': 2, 'Filosofia':3, 'LinguaInglese':3, 'Latino':3, 'Italiano':4, 'Fisica':3, 'DisegnoArte':2, 'Scienzemotorie':2, 'Religione':1},
        ('Scientifico', 4): {'Matematica': 4, 'Scienzenaturali': 3, 'Storia': 2, 'Filosofia':3, 'LinguaInglese':3, 'Latino':3, 'Italiano':4, 'Fisica':3, 'DisegnoArte':2, 'Scienzemotorie':2, 'Religione':1},
        ('Scientifico', 5): {'Matematica': 4, 'Scienzenaturali': 3, 'Storia': 2, 'Filosofia':3,  'LinguaInglese':3, 'Latino':3, 'Italiano':4, 'Fisica':3, 'DisegnoArte':2, 'Scienzemotorie':2, 'Religione':1},
        ('ScienzeApplicate', 1): {'Matematica': 5, 'Scienzenaturali': 3, 'Geostoria': 3, 'LinguaInglese':3, 'Latino':3, 'Italiano':4, 'Fisica':2, 'DisegnoArte':2, 'Scienzemotorie':2, 'Religione':1, 'Informatica':2},
        ('ScienzeApplicate', 2): {'Matematica': 4, 'Scienzenaturali': 4, 'Geostoria': 3, 'LinguaInglese':3, 'Latino':3, 'Italiano':4, 'Fisica':2, 'DisegnoArte':2, 'Scienzemotorie':2, 'Religione':1, 'Informatica':2},
        ('ScienzeApplicate', 3): {'Matematica': 4, 'Scienzenaturali': 5, 'Storia': 2, 'Filosofia':2, 'LinguaInglese':3, 'Latino':3, 'Italiano':4, 'Fisica':3, 'DisegnoArte':2, 'Scienzemotorie':2, 'Religione':1, 'Informatica':2},
        ('ScienzeApplicate', 4): {'Matematica': 4, 'Scienzenaturali': 5, 'Storia': 2, 'Filosofia':2, 'LinguaInglese':3, 'Latino':3, 'Italiano':4, 'Fisica':3, 'DisegnoArte':2, 'Scienzemotorie':2, 'Religione':1, 'Informatica':2},
        ('ScienzeApplicate', 5): {'Matematica': 4, 'Scienzenaturali': 5, 'Storia': 2, 'Filosofia':2,  'LinguaInglese':3, 'Latino':3, 'Italiano':4, 'Fisica':3, 'DisegnoArte':2, 'Scienzemotorie':2, 'Religione':1, 'Informatica':2},
        ('EconomicoSociale_FRA', 1): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':3, 'LinguaFrancese':3, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_FRA', 2): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':3, 'LinguaFrancese':3, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_FRA', 3): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia':2, 'LinguaInglese':3, 'LinguaFrancese':3, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_FRA', 4): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia':2, 'LinguaInglese':3, 'LinguaFrancese':3, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_FRA', 5): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia':2,  'LinguaInglese':3, 'LinguaFrancese':3, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_SPA', 1): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':3, 'LinguaSpagnola':3, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_SPA', 2): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':3, 'LinguaSpagnola':3, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_SPA', 3): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia':2, 'LinguaInglese':3, 'LinguaSpagnola':3, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_SPA', 4): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia':2, 'LinguaInglese':3, 'LinguaSpagnola':3, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_SPA', 5): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia':2,  'LinguaInglese':3, 'LinguaSpagnola':3, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_TED', 1): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':3, 'LinguaTedesca':3, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_TED', 2): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':3, 'LinguaTedesca':3, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_TED', 3): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia':2, 'LinguaInglese':3, 'LinguaTedesca':3, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_TED', 4): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia':2, 'LinguaInglese':3, 'LinguaTedesca':3, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('EconomicoSociale_TED', 5): {'Scienzeumane':3, 'DirittoEconomia': 3,'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia':2,  'LinguaInglese':3, 'LinguaTedesca':3, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('ScienzeUmane', 1): {'Scienzeumane':4, 'DirittoEconomia': 2,'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':3, 'Latino':3, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('ScienzeUmane', 2): {'Scienzeumane':4, 'DirittoEconomia': 2,'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':3, 'Latino':3, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('ScienzeUmane', 3): {'Scienzeumane':5, 'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'Storia': 2, 'Filosofia':3, 'LinguaInglese':3, 'Latino':2, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('ScienzeUmane', 4): {'Scienzeumane':5, 'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'Storia': 2, 'Filosofia':3, 'LinguaInglese':3, 'Latino':2, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('ScienzeUmane', 5): {'Scienzeumane':5, 'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'Storia': 2, 'Filosofia':3,  'LinguaInglese':3, 'Latino':2, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('Linguistico_FRA_SPA', 1): {'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':4, 'LinguaFrancese':3, 'LinguaSpagnola':3,'Latino':2, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('Linguistico_FRA_SPA', 2): {'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':4, 'LinguaFrancese':3, 'LinguaSpagnola':3,'Latino':2, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('Linguistico_FRA_SPA', 3): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese':3, 'LinguaFrancese':4, 'LinguaSpagnola':4, 'Storia': 2, 'Filosofia':2, 'Latino':2, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('Linguistico_FRA_SPA', 4): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese':3, 'LinguaFrancese':4, 'LinguaSpagnola':4, 'Storia': 2, 'Filosofia':2, 'Latino':2, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('Linguistico_FRA_SPA', 5): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese':3, 'LinguaFrancese':4, 'LinguaSpagnola':4, 'Storia': 2, 'Filosofia':2, 'Latino':2, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('Linguistico_FRA_TED', 1): {'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':4, 'LinguaFrancese':3, 'LinguaTedesca':3,'Latino':2, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('Linguistico_FRA_TED', 2): {'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese':4, 'LinguaFrancese':3, 'LinguaTedesca':3,'Latino':2, 'Italiano':4, 'Scienzemotorie':2, 'Religione':1},
        ('Linguistico_FRA_TED', 3): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese':3, 'LinguaFrancese':4, 'LinguaTedesca':4, 'Storia': 2, 'Filosofia':2, 'Latino':2, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('Linguistico_FRA_TED', 4): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese':3, 'LinguaFrancese':4, 'LinguaTedesca':4, 'Storia': 2, 'Filosofia':2, 'Latino':2, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
        ('Linguistico_FRA_TED', 5): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese':3, 'LinguaFrancese':4, 'LinguaTedesca':4, 'Storia': 2, 'Filosofia':2, 'Latino':2, 'Italiano':4, 'Arte':2, 'Scienzemotorie':2, 'Religione':1},
    }
    #print([j.keys() for k,j in curriculum_subject_hours.items()])
    curriculum_subjects=list(set([s for j in curriculum_subject_hours.values() for s in j.keys()]))
    curricula=[Curriculum(j, curriculum_subject_hours) for j in set(k for k,r in curriculum_subject_hours.keys())]
    return curricula, curriculum_subjects, curriculum_subject_hours

def create_school_classes_with_curriculum(curricula, curriculaclasses={'Scientifico':2, 'ScienzeApplicate':0, 'ScienzeUmane':0, 'EconomicoSociale_FRA':0, 'EconomicoSociale_SPA':0, 'EconomicoSociale_TED':0, 'Linguistico_FRA_TED':2, 'Linguistico_FRA_SPA':0}):
    sections = [chr(ord('A') + i) for i in range(sum([j for j in curriculaclasses.values()]))]  # Sections A to P
    #years = [j+1 for j in range(numyears)]  # Example: Year 1 and Year 2
    iterator=0
    school_classes=[]
    print([j.name for j in curricula])
    for curriculum, nsections in curriculaclasses.items():
        cwithname = list(filter(lambda elem: elem.name == curriculum, curricula))[0]
        #cwithname=cwithname[0
        for section in range(nsections):
            for year in cwithname.plan.keys():
                school_classes.append(SchoolClass(sections[iterator], year, cwithname))
            iterator+=1
    return school_classes


def choose_random_free_day(day_weights):
    days = list(day_weights.keys())
    weights = list(day_weights.values())
    free_day = random.choices(days, weights)[0]  # Selects a day based on the provided weights
    return free_day

def calculate_teachers_needed(school_classes):
    total_hours_per_subject = {}
    #total_hours_per_subject_group={}
    # Calculate total hours required per subject
    for classe in school_classes:
        timetable=classe.subjects

        for subject, hours in timetable.items():
            if subject not in total_hours_per_subject:
                total_hours_per_subject[subject] = hours
            else:
                total_hours_per_subject[subject] += hours

    # Determine the number of teachers needed per subject
    #hours_needed_per_subject = {subject: (lambda x,y: ceil(x/y))(hours , max_hours_per_teacher) for subject, hours in total_hours_per_subject.items()}
    return total_hours_per_subject

# Example usage
# This assumes you have defined the `generate_curriculum_subjects` and `create_school_classes_with_curriculum` functions
# max_hours_per_teacher = 10
# teachers_needed_per_subject = calculate_teachers_needed(generate_curriculum_subjects, create_school_classes_with_curriculum, max_hours_per_teacher)
# print("Teachers needed per subject:", teachers_needed_per_subject)


def assign_teachers_to_classes(school_classes, teachers, curriculum_subject_hours):
    allclasses=copy.deepcopy(school_classes)
    #allclasses=
    iterator=0
    while len(allclasses)>0 and iterator<2000:
        iterator+=1
        myclass=random.choice(allclasses)
        allclasses.remove(myclass)
    #for school_class in school_classes:
        curriculum_year = (myclass.curriculum, myclass.year)
        subject_hours = curriculum_subject_hours.get(curriculum_year, {})
        for subject_name, weekly_hours in subject_hours.items():
            # Shuffle the list of teachers for randomness
            shuffled_teachers = random.sample(teachers, len(teachers))
            for teacher in shuffled_teachers:
                if subject_name in random.choices(list(teacher.weights.keys()), list(teacher.weights.values())) and teacher.max_hours - teacher.assigned_hours >= weekly_hours:
                    myclass.subjects[subject_name] = teacher
                    teacher.assigned_hours += weekly_hours
                    break


# def assign_teachers_to_classes(school_classes, teachers):
#     for school_class in school_classes:
#         for subject_name in school_class.subjects.keys():
#             for teacher in teachers:
#                 if subject_name in teacher.subject_group.subjects:
#                     # Only consider weights for subjects that are in both the teacher's subject group and the class's needs
#                     applicable_weights = {subj: weight for subj, weight in teacher.weights.items() if subj in teacher.subject_group.subjects}
#                     if applicable_weights:
#                         # Choose subject based on weights
#                         chosen_subject = random.choices(list(applicable_weights.keys()), weights=list(applicable_weights.values()))[0]
#                         if chosen_subject == subject_name and teacher.max_hours - teacher.assigned_hours >= school_class.subjects[subject_name].weekly_hours:
#                             school_class.subjects[subject_name] = teacher
#                             teacher.assigned_hours += school_class.subjects[subject_name].weekly_hours
#                             break

def generate_required_teachers(hours_needed_per_subject, day_weights, cconcorsopersubject, cconcorso_list):
    teachers = []
    teacher_id = 1
    allnames=[]

    for subject, count in hours_needed_per_subject.items():
        weights=cconcorsopersubject[subject]
        totore=count
        while totore>0:
            mychoicecconcorso=random.choices([k for k,j in weights.items()],[j for k,j in weights.items()])[0] #choice of classe di concorso
            free_day = choose_random_free_day(day_weights)  # Choose a free day for each teacher
            while True:
                teacher_name = fake.name()
                if teacher_name not in allnames:
                    allnames.append(teacher_name)
                    break
            maxhours=random.choices([18 for j in range(30)])[0]
            birth=fake.date_of_birth(minimum_age=25, maximum_age=67)
            #subject_group, max_hours, free_day, weights=None)
            teachers.append(Teacher(teacher_name, list(filter(lambda x : x.name==mychoicecconcorso, cconcorso_list))[0], maxhours, free_day, birth=birth))
            teacher_id += 1
            totore-=maxhours
    return teachers

def createmodelvariables(allclasses, allteachers, cconcorsopersubject, assignment_vars):
    #assignment_vars = []
    for iclass in allclasses:
        for isubject, ihours in iclass.subjects.items():
            for teacher in allteachers:
                if teacher.subject_group.name in cconcorsopersubject[isubject]:
                    a = model.NewBoolVar('%s_%s_%s' %
                                        (iclass.name, isubject, teacher.name))
                    deepset(iclass.docenti, (ihours, a), isubject, teacher.name)
                    deepset(teacher.cattedra, (ihours, a), isubject, iclass.name)
                    assignment_vars.append(a)


def enforcemaxhoursperteacher(allteachers, allclasses, docentedictclasse, docentedictcurriculum):
    cattedracompleta=[]
    scoredict={}
    fewclasses=[]
    manycurricula=[]
    #curriculadict={}
    #print(docentedictcurriculum)
    #exit()
    for teacher in allteachers:

        sumhours=[]

        classdict=docentedictclasse.get(teacher.name, None)
        for iclass, many in classdict.items():
           temp=model.NewBoolVar('hasclass_%s_%s' % (teacher.name, iclass))
           model.AddBoolOr(many).OnlyEnforceIf(temp)
           model.AddBoolAnd([j.Not() for j in many]).OnlyEnforceIf(temp.Not())
           teacher.totclasses=teacher.totclasses+temp
        fewclasses.append(teacher.totclasses)

        curriculum=docentedictcurriculum.get(teacher.name, None)
        for icurr, many in curriculum.items():
           temp=model.NewBoolVar('hascurr_%s_%s' % (teacher.name, icurr))
           model.AddBoolOr(many).OnlyEnforceIf(temp)
           model.AddBoolAnd([j.Not() for j in many]).OnlyEnforceIf(temp.Not())
           teacher.totcurricula=teacher.totcurricula+temp
        manycurricula.append(teacher.totcurricula)

        for subject, classdict in teacher.cattedra.items():
            for iclass, value in classdict.items():
                thisclass=list(filter(lambda x: x.name==iclass, allclasses))[0]
                thiscurriculum=thisclass.curriculum
                newscore=[value[0]*curriculum_scores[thiscurriculum]*value[1]]
                sumhours.append(value[0]*value[1])
                oldscore=deepget(scoredict,[], teacher.name)
                deepset(scoredict, newscore+oldscore, teacher.name)

        actualhours=model.NewIntVar(0,30,'actual_hours_%s' % teacher.name)
        teacher.actual_hours=actualhours
        model.Add(actualhours==sum(sumhours))
        model.Add(actualhours<=teacher.max_hours)

        mismatch=model.NewIntVar(-25,25,'mism_%s' % teacher.name)
        mismatchsq=model.NewIntVar(0,1000,'mismsq_%s' % teacher.name)
        mismatchqq=model.NewIntVar(0,1000000,'mismsq_%s' % teacher.name)
        model.Add(mismatch==teacher.max_hours-teacher.actual_hours)
        #model.AddMultiplicationEquality(mismatchsq, [mismatch, mismatch])
        #model.AddMultiplicationEquality(mismatchqq, [mismatchsq, mismatchsq])

        cattedracompleta.append(mismatch)

    return sum(cattedracompleta), scoredict, sum(fewclasses), sum(manycurricula)

def enforcecattedracoperta(allclasses, allteachers):

    docentedictclasse={}
    docentedictcurriculum={}

    for classe in allclasses:
      for subject, docenti in classe.docenti.items():
         assignedsubject=[]
         #print([subject,docenti.items()])
         for docente, value in docenti.items():
            assignedsubject.append(value[1])
            a=copy.deepcopy(deepget(docentedictclasse, [], docente, classe.name))
            deepset(docentedictclasse, a+[value[1]], docente, classe.name)
            b=copy.deepcopy(deepget(docentedictcurriculum,[],  docente, classe.curriculum.split('_')[0]))
            deepset(docentedictcurriculum, b+[value[1]], docente, classe.curriculum.split('_')[0])
         model.Add(sum(assignedsubject)==1)

    return docentedictclasse, docentedictcurriculum


def enforce_equal_scores(scoredict, allteachers):
   totalscore=model.NewIntVar(-10000,100000, 'totscore')
   totalhours=model.NewIntVar(0,100000,'stotalhours')
#    totalscoremismatch=model.NewIntVar(0,100000000,'totalscoremismatch')
   sumscore=[]
   numteacherhours=[]

   for teacher, score in scoredict.items():
      thisteacher=list(filter(lambda x: x.name==teacher, allteachers))[0]
      sumscore=sumscore+score #score è una lista
      numteacherhours.append(thisteacher.actual_hours)

   model.Add(totalhours==sum(numteacherhours))
   model.Add(sum(sumscore)==totalscore)

   mismatches=[]
   runner=0
   for teacher, score in scoredict.items():
      thisteacher=list(filter(lambda x: x.name==teacher, allteachers))[0]
      iscore=model.NewIntVar(-10000,3000000,'checkscore_%s' % teacher)
      model.Add(iscore==sum(score))
      thisteacher.totscore=iscore
      scoremismatch=model.NewIntVar(-30000000,30000000,'scoremismatch_%s' % teacher)
      scoremismatchsq=model.NewIntVar(-30000000,30000000, 'scoremismatchsq_%s' % teacher)
      scoretimesthours=model.NewIntVar(-10000000,300000000,'scoretimesthours_%s' % teacher)
      tscoretimeshours=model.NewIntVar(-10000000,300000000,'tscoretimeshours_%s' % teacher)
      model.AddMultiplicationEquality(scoretimesthours, [iscore,totalhours])
      model.AddMultiplicationEquality(tscoretimeshours, [totalscore,thisteacher.actual_hours])
      model.Add(scoremismatch==scoretimesthours-tscoretimeshours)
      positive=model.NewBoolVar('aid1 %d' % runner)
      runner+=1
      model.Add(scoremismatchsq==scoremismatch).OnlyEnforceIf(positive)
      model.Add(scoremismatchsq==-scoremismatch).OnlyEnforceIf(positive.Not())
      model.Add(scoremismatch>=0).OnlyEnforceIf(positive)
      model.Add(scoremismatch<0).OnlyEnforceIf(positive.Not())
      #model.AddMultiplicationEquality(scoremismatchsq,[scoremismatch, scoremismatch])
      mismatches.append(scoremismatchsq)
#    model.Add(sum(mismatches)==totalscoremismatch)
   return sum(mismatches)



def deepset(dictionary, value, *args):
  aid = dictionary
  for s in range(len(args)):
    try:
      temp = aid[args[s]]
    except Exception:
      aid[args[s]] = {}
      temp = aid[args[s]]
    if s == len(args) - 1:
      aid[args[s]] = value
    else:
      aid = temp

def deepget(dictionary, default, *args):
  aid = dictionary
  for s in range(len(args)):
    try:
      temp = aid[args[s]]
    except Exception:
      return default
    if s == len(args) - 1:
      return(aid[args[s]])
    else:
      aid = temp

def print_cattedre(allteachers, solver):
    cattedre={}
    classi={}
    for teacher in allteachers:
        cattedre[teacher.name]={}
        for subject, classdict in teacher.cattedra.items():
            for iclass, value in classdict.items():
               if solver.Value(value[1]):
                  deepset(cattedre, value[0], teacher.name, iclass, subject)
                  deepset(classi, (teacher.name, value[0]), iclass, subject)

    print(cattedre)
    print("********")

    for teacher, diction in cattedre.items():
       thisteacher=list(filter(lambda x: x.name==teacher, allteachers))[0]
       print("prof. %s, classe di concorso %s" % (thisteacher.name, thisteacher.subject_group.name))
       print("n. di classi %d" % solver.Value(thisteacher.totclasses))
       print("tot. indirizzi: %d" % solver.Value(thisteacher.totcurricula))
       print("tot. ore: %d" % solver.Value(thisteacher.actual_hours))
       print("tot. score: %d" % solver.Value(thisteacher.totscore))
       for classe, dictclass in diction.items():
            for isubj, ore in dictclass.items():
                print("%s, %s, %d" % (classe, isubj, ore))
       print("\n")

    return cattedre, classi

def map_day(day_str):
    days = {'Monday':1, 'Tuesday':2, 'Wednesday':3, 'Thursday':4, 'Friday':5, 'Saturday':6}
    return days[day_str]

def random_other_day(current):
    days = list(day_weights.keys())
    for j in current:
        if j in days:
            days.remove(j)
    return random.choice(days)

if __name__=="__main__":
    allcurr, allsubj, csubj=generate_curriculum_subjects()
    cconcorsodict, cconcorso_list, cconcorsopersubject=generate_subject_groups()
    allclasses=create_school_classes_with_curriculum(allcurr)

    hoursneeded=calculate_teachers_needed(allclasses)
    allteachers=generate_required_teachers(hoursneeded, day_weights, cconcorsopersubject, cconcorso_list)

    assignment_vars=[]
    createmodelvariables(allclasses, allteachers, cconcorsopersubject, assignment_vars)
    docentedictclasse, docentedictcurriculum=enforcecattedracoperta(allclasses, allteachers)
    cattedracompleta, scoredict, fewclasses, manycurricula=enforcemaxhoursperteacher(allteachers, allclasses, docentedictclasse, docentedictcurriculum)
    scoremismatch=enforce_equal_scores(scoredict, allteachers)
    #model.Minimize(scoremismatch)  # Removed

    import json, pickle

    if(False):
        with open('solutionmock.pkl', 'rb') as file:
            ls = pickle.load(file)

        for key, value in ls.items():
            wclasse=key[0]
            wsubj=key[1]
            wdoc=key[2]
            tclass=list(filter(lambda x: x.name==wclasse,allclasses))[0]
            variable=tclass.docenti[wsubj][wdoc][1]
            model.AddHint(variable, value)

    solver = cp_model.CpSolver()
    solver.parameters.log_search_progress = True
    solver.parameters.num_search_workers = 32
    solver.parameters.max_time_in_seconds = maxtime

    # Phase 1: Minimize cattedracompleta
    model.Minimize(cattedracompleta)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("No solution found in phase 1.")

    thecattedre, theclassi=print_cattedre(allteachers, solver)

    min_cat = solver.ObjectiveValue()
    model.Add(cattedracompleta <= int(min_cat))
    model.Proto().ClearField('objective')
    model.Proto().solution_hint.Clear()

    for var in assignment_vars:
        model.AddHint(var, solver.Value(var))


    #print(thecattedre)
    # Phase 2: Minimize fewclasses
    model.Minimize(fewclasses)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("No solution found in phase 2.")

    thecattedre, theclassi=print_cattedre(allteachers, solver)

    min_few = solver.ObjectiveValue()
    model.Add(fewclasses <= int(min_few))
    model.Proto().ClearField('objective')
    model.Proto().solution_hint.Clear()

    for var in assignment_vars:
        model.AddHint(var, solver.Value(var))

    #print(thecattedre)
    # Phase 3: Maximize manycurricula (minimize -manycurricula)
    model.Minimize(-manycurricula)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("No solution found in phase 3.")

    thecattedre, theclassi=print_cattedre(allteachers, solver)

    min_neg_many = solver.ObjectiveValue()
    model.Add(manycurricula >= int(-min_neg_many))
    model.Proto().ClearField('objective')
    model.Proto().solution_hint.Clear()

    for var in assignment_vars:
        model.AddHint(var, solver.Value(var))

    # Phase 4: Minimize scoremismatch
    solver.parameters.max_time_in_seconds = maxtime # Adjust remaining time if needed
    model.Minimize(scoremismatch)
    status = solver.Solve(model)
    print(solver.ResponseStats())

    thecattedre, theclassi=print_cattedre(allteachers, solver)
    #print(thecattedre)

    solution = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for iclass in allclasses:
           for subj, docenti in iclass.docenti.items():
              for idoc, value in docenti.items():
                solution[(iclass.name, subj, idoc)]=solver.Value(value[1])
        with open('solutionmock.pkl', 'wb') as file:
            pickle.dump(solution, file)
    else:
        print("No solution found.")

    profs = {}
    for teacher in allteachers:
        free1 = teacher.free_day
        free2 = random_other_day([free1])
        free3 = random_other_day([free1, free2])
        profs[teacher.name] = {'classi': {}, 'glibero': [map_day(free1), map_day(free2), map_day(free3)] }

    for (class_name, subj, teacher_name), val in solution.items():
        if val:
            iclass = next(c for c in allclasses if c.name == class_name)
            hours = iclass.subjects[subj]
            if class_name not in profs[teacher_name]['classi']:
                profs[teacher_name]['classi'][class_name] = {}
            profs[teacher_name]['classi'][class_name][subj] = {'ore': hours}

    with open('profs.pkl', 'wb') as file:
        pickle.dump(profs, file)
