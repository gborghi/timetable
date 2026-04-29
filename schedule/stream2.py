import streamlit as st
import pickle
import pandas as pd
from streamlit_elements import elements, dashboard, mui

# Load data
with open('profs.pkl', 'rb') as file:
    profs = pickle.load(file)
classes = sorted(list(set(cl for teacher in profs for cl in profs[teacher]['classi'])))
prof_list = sorted(profs.keys())

# Class to profs mapping
class_profs = {cl: set() for cl in classes}
for prof in profs:
    for cl in profs[prof]['classi']:
        class_profs[cl].add(prof)

days = list(range(1, 7))
hours = list(range(8, 15))
day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

if 'solution' not in st.session_state:
    with open('solution_timetable.pkl', 'rb') as file:
        st.session_state.solution = pickle.load(file)

if 'layouts' not in st.session_state:
    st.session_state.layouts = {}

if 'lectures_lists' not in st.session_state:
    st.session_state.lectures_lists = {}

st.title("School Timetable Viewer")

view_type = st.selectbox("View by:", ["Class", "Professor"])

selected = None
if view_type == "Class":
    selected = st.selectbox("Select Class:", classes)
elif view_type == "Professor":
    selected = st.selectbox("Select Professor:", prof_list)

if selected:
    state_key = f"{view_type}_{selected}"

    if state_key not in st.session_state.layouts:
        layout = []
        lectures_list = []
        id_counter = 0

        # Add static corner
        layout.append(dashboard.Item("corner", 0, 0, 1, 1, static=True))

        # Add static hour labels
        for i, h in enumerate(hours):
            layout.append(dashboard.Item(f"hour_{h}", i + 1, 0, 1, 1, static=True))

        # Add static day labels
        for i, dn in enumerate(day_names):
            layout.append(dashboard.Item(f"day_{i+1}", 0, i + 1, 1, 1, static=True))

        if view_type == "Class":
            for prof in profs:
                if selected in profs[prof]['classi']:
                    for subj in profs[prof]['classi'][selected]:
                        for day in days:
                            for hour in hours:
                                key = (prof, selected, subj, day, hour)
                                if st.session_state.solution.get(key, 0) == 1:
                                    id_counter += 1
                                    item_key = f"item_{id_counter}"
                                    layout.append(dashboard.Item(item_key, (hour - 8) + 1, day, 1, 1))
                                    lectures_list.append({"id": item_key, "prof": prof, "subj": subj, "day": day, "hour": hour})
        else:  # Professor
            for cl in profs[selected]['classi']:
                for subj in profs[selected]['classi'][cl]:
                    for day in days:
                        for hour in hours:
                            key = (selected, cl, subj, day, hour)
                            if st.session_state.solution.get(key, 0) == 1:
                                id_counter += 1
                                item_key = f"item_{id_counter}"
                                layout.append(dashboard.Item(item_key, (hour - 8) + 1, day, 1, 1))
                                lectures_list.append({"id": item_key, "cl": cl, "subj": subj, "day": day, "hour": hour})

        st.session_state.layouts[state_key] = layout
        st.session_state.lectures_lists[state_key] = lectures_list

    layout = st.session_state.layouts[state_key]
    lectures_list = st.session_state.lectures_lists[state_key]

    def handle_layout_change(updated_layout):
        conflicts = False
        for item in updated_layout:
            old_item = next((it for it in layout if it.i == item.i), None)
            if old_item and (item.x != old_item.x or item.y != old_item.y):
                if item.x < 1 or item.y < 1:
                    item.x = old_item.x
                    item.y = old_item.y
                    conflicts = True
                    continue
                new_hour = item.x + 7  # since x starts from 1, hour = x +7 ? Wait, x=1 -> hour=8, so item.x +7
                #wait, hours=8 to14, x=1 to7 -> hour = item.x +7
                #1+7=8, 2+7=9,...7+7=14 yes.
                new_day = item.y  # y=1 to6 -> day=1 to6
                lec = next(l for l in lectures_list if l["id"] == item.i)
                if view_type == "Class":
                    prof = lec["prof"]
                    subj = lec["subj"]
                    cl = selected
                    # Check prof conflict
                    conflict = any(
                        st.session_state.solution.get((prof, any_cl, any_subj, new_day, new_hour), 0) == 1
                        for any_cl in profs[prof]['classi']
                        for any_subj in profs[prof]['classi'][any_cl]
                    )
                else:  # Professor
                    prof = selected
                    subj = lec["subj"]
                    cl = lec["cl"]
                    # Check class conflict
                    conflict = any(
                        st.session_state.solution.get((any_prof, cl, any_subj, new_day, new_hour), 0) == 1
                        for any_prof in class_profs[cl]
                        for any_subj in profs[any_prof]['classi'][cl]
                    )

                if conflict:
                    item.x = old_item.x
                    item.y = old_item.y
                    conflicts = True
                else:
                    old_day = lec["day"]
                    old_hour = lec["hour"]
                    old_key = (prof, cl, subj, old_day, old_hour)
                    new_key = (prof, cl, subj, new_day, new_hour)
                    st.session_state.solution[old_key] = 0
                    st.session_state.solution[new_key] = 1
                    lec["day"] = new_day
                    lec["hour"] = new_hour

        st.session_state.layouts[state_key] = updated_layout
        if conflicts:
            st.warning("Move caused a conflict and was reverted.")

    with elements("dashboard"):
        dashboard.Grid(layout, rowHeight=100, cols={"lg": 7, "xs":7}, onLayoutChange=handle_layout_change)
        # Corner
        with mui.Paper(key="corner", sx={"height": "100%", "display": "flex", "justifyContent": "center", "alignItems": "center"}):
            mui.Typography("Day / Hour")

        # Hour labels
        for h in hours:
            with mui.Paper(key=f"hour_{h}", sx={"height": "100%", "display": "flex", "justifyContent": "center", "alignItems": "center"}):
                mui.Typography(f"{h}:00")

        # Day labels
        for i, dn in enumerate(day_names):
            with mui.Paper(key=f"day_{i+1}", sx={"height": "100%", "display": "flex", "justifyContent": "center", "alignItems": "center"}):
                mui.Typography(dn)

        for lec in lectures_list:
            with mui.Paper(key=lec["id"], sx={"height": "100%", "display": "flex", "flexDirection": "column", "justifyContent": "center", "alignItems": "center"}):
                if view_type == "Class":
                    mui.Typography(lec["prof"])
                    mui.Typography(lec["subj"])
                else:
                    mui.Typography(lec["cl"])
                    mui.Typography(lec["subj"])
