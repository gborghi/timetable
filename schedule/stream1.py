import streamlit as st
import pickle
import pandas as pd

# Load data
with open('profs.pkl', 'rb') as file:
    profs = pickle.load(file)
classes = sorted(list(set(cl for teacher in profs for cl in profs[teacher]['classi'])))
prof_list = sorted(profs.keys())

with open('solution_timetable.pkl', 'rb') as file:
    solution = pickle.load(file)
#print(solution)

days = list(range(1, 7))
hours = list(range(8, 15))

st.title("School Timetable Viewer")

view_type = st.selectbox("View by:", ["Class", "Professor"])

if view_type == "Class":
    selected_class = st.selectbox("Select Class:", classes)
    if selected_class:
        timetable = {day: {hour: "" for hour in hours} for day in days}
        for prof in profs:
            if selected_class in profs[prof]['classi']:
                print(prof)
                for subj in profs[prof]['classi'][selected_class]:
                    for day in days:
                        for hour in hours:
                            key = (prof, selected_class, subj, day, hour)
                            if key in solution and solution[key] == 1:
                                timetable[day][hour] = f"{prof} - {subj}"

        df = pd.DataFrame(timetable).T
        print(df)
        df.columns = [f"Hour {h}" for h in hours]
        df.index.name = "Day"
        st.dataframe(df.style.set_properties(**{'text-align': 'center'}))
elif view_type == "Professor":
    selected_prof = st.selectbox("Select Professor:", prof_list)
    if selected_prof:
        timetable = {day: {hour: "" for hour in hours} for day in days}
        for cl in profs[selected_prof]['classi']:
            for subj in profs[selected_prof]['classi'][cl]:
                for day in days:
                    for hour in hours:
                        key = (selected_prof, cl, subj, day, hour)
                        if key in solution and solution[key] == 1:
                            timetable[day][hour] = f"{cl} - {subj}"

        df = pd.DataFrame(timetable).T
        df.columns = [f"Hour {h}" for h in hours]
        df.index.name = "Day"
        st.dataframe(df.style.set_properties(**{'text-align': 'center'}))
