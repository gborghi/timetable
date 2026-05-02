// Canonical TypeScript types for the piTantum frontend.
//
// These mirror the Pydantic schemas in `webui/backend/schemas.py` and
// the SQLAlchemy models in `webui/backend/models.py`. Keep in sync
// manually; the long-term plan (improvements.md 2.10 P2) is to
// auto-generate them from the FastAPI OpenAPI schema via
// `openapi-typescript`.

// ============================================================
// Constraint state taxonomy (5 levels + forbidden alias)
// ============================================================

export type ConstraintLevel =
  | "allowed"
  | "soft"
  | "preferred"
  | "hard"
  | "forbidden"
  | "enforced";

/** 4 kinds for *logical* constraints (no allowed / forbidden). */
export type LogicalKind = "hard" | "soft" | "preferred" | "enforced";

// ============================================================
// Availability cell (matrix cell)
// ============================================================

export interface UnavailabilitySlot {
  day: number;          // 1..6 (Mon..Sat)
  hour: number;         // 8..13
  state: ConstraintLevel;
  soft_penalty: number;
  reason?: string | null;
}

// ============================================================
// Subjects
// ============================================================

export interface SubjectClassroomPref {
  classroom_name: string;
  state: ConstraintLevel;
  weight: number;
}

export interface SubjectBase {
  name: string;
  pretty_name?: string | null;
  notes?: string | null;
  distribute_days_weight: number;
  dual_hours_weight: number;
  no_sixth_hour_weight: number;
  preferred_band_start?: number | null;
  preferred_band_end?: number | null;
  preferred_band_weight: number;
}

export interface Subject extends SubjectBase {
  id: number;
  classroom_prefs: SubjectClassroomPref[];
}

export interface SubjectGroupWeight {
  id?: number;
  subject: string;
  group_name: string;
  weight: number;
}

// ============================================================
// Teachers
// ============================================================

export interface TeacherClassroomPref {
  classroom_name: string;
  state: ConstraintLevel;
  weight: number;
}

export interface TeacherBase {
  name: string;
  last_name?: string | null;
  first_name?: string | null;
  nickname?: string | null;
  matricola?: string | null;
  group?: string | null;
  max_hours: number;
  completion_hours: number;
  exemption_hours: number;
  graduatoria_score?: number | null;
  free_day?: string | null;
  max_consecutive: number;
  notes?: string | null;
  pref_no_buchi_weight: number;
  pref_no_five_weight: number;
  pref_no_one_weight: number;
  preferred_days_csv?: string | null;
}

export interface Teacher extends TeacherBase {
  id: number;
  subjects: string[];
  unavailability: UnavailabilitySlot[];
  mandatory_free_days: number[];
  compatible_classes: string[];
  classroom_prefs: TeacherClassroomPref[];
  // Server-derived fields surfaced by /api/teachers
  scheduled_hours?: number;
  n_classes?: number;
  soft_penalty_total?: number;
}

// ============================================================
// School Classes
// ============================================================

export interface ClassSubject {
  subject: string;
  hours_per_week: number;
}

export interface ClassBase {
  name: string;
  nickname?: string | null;
  year: number;
  section?: string | null;
  curriculum?: string | null;
  curriculum_id?: number | null;
  n_students: number;
  notes?: string | null;
  hard_entry_at_8: boolean;
  hard_exit_after_12: boolean;
  hard_no_holes: boolean;
  hard_dual_math: boolean;
  hard_dual_italian: boolean;
  hard_motorie_pairs: boolean;
  hard_max_6_per_day: boolean;
  soft_minimize_sixth_weight: number;
}

export interface SchoolClass extends ClassBase {
  id: number;
  subjects: ClassSubject[];
  unavailability: UnavailabilitySlot[];
  // Derived
  ore_totali?: number;
  n_subjects?: number;
}

// ============================================================
// Classrooms
// ============================================================

export type RoomKind =
  | "standard"
  | "lab_chimica"
  | "lab_fisica"
  | "lab_informatica"
  | "lab_linguistico"
  | "palestra"
  | "biblioteca"
  | "aula_speciale";

export interface ClassroomSubjectPref {
  subject: string;
  state: ConstraintLevel;
  weight: number;
  required?: boolean;
}

export interface ClassroomClassPref {
  class_name: string;
  state: ConstraintLevel;
  weight: number;
  is_home?: boolean;
}

export interface Classroom {
  id: number;
  name: string;
  kind: RoomKind;
  capacity: number;
  multi_class: boolean;
  multi_class_max: number;
  multi_class_pref: number;
  multi_class_pref_weight: number;
  notes?: string | null;
  subject_prefs: ClassroomSubjectPref[];
  class_prefs: ClassroomClassPref[];
  unavailability: UnavailabilitySlot[];
  tags?: string[];
}

export interface ClassroomTag {
  id: number;
  name: string;
  description?: string | null;
  n_classrooms?: number;
}

// ============================================================
// Curriculum
// ============================================================

export interface CurriculumHour {
  year: number;
  subject: string;
  hours_per_week: number;
}

export interface Curriculum {
  id: number;
  code: string;
  name?: string | null;
  description?: string | null;
  notes?: string | null;
  score: number;
  hours: CurriculumHour[];
  // Derived
  n_classes?: number;
}

// ============================================================
// Students + Groups
// ============================================================

export type Gender = "M" | "F" | "other" | null;

export interface StudentBase {
  last_name: string;
  first_name: string;
  nickname?: string | null;
  birth_date?: string | null;     // ISO date
  gender?: Gender;
  email?: string | null;
  student_code?: string | null;
  class_id?: number | null;
  notes?: string | null;
}

export interface Student extends StudentBase {
  id: number;
  // Derived
  class_name?: string | null;
  n_groups?: number;
}

export interface GroupSubjectHours {
  subject: string;
  hours_per_week: number;
}

export interface StudyGroup {
  id: number;
  name: string;
  nickname?: string | null;
  kind: "splitting" | "merging" | string;
  description?: string | null;
  notes?: string | null;
  student_ids: number[];
  subject_hours: GroupSubjectHours[];
  // Derived
  n_students?: number;
  n_classes_touched?: number;
}

// ============================================================
// Coteaching
// ============================================================

export interface CoteachingRule {
  id: number;
  class_name: string;
  subject: string;
  required: boolean;
  weight: number;
  n_teachers: number;
  teachers: string[];
}

// ============================================================
// Assignments
// ============================================================

export interface Assignment {
  id: number;
  teacher_name: string;
  class_name: string;
  subject: string;
  hours: number;
  locked: boolean;
}

// ============================================================
// Solutions, lessons, schedule
// ============================================================

export interface Solution {
  id: number;
  name: string;
  kind: string;
  obj_value: number;
  metrics: Record<string, number | string>;
  is_active: boolean;
  created_at?: string;
  notes?: string | null;
}

export interface ScheduleCell {
  lesson_id: number;
  teachers: string[];
  subjects: string[];
  classroom?: string | null;
}

export interface ScheduleTeacherCell {
  lesson_id: number;
  class_name: string;
  subject: string;
  classroom?: string | null;
}

export interface ScheduleRoomCell {
  lesson_id: number;
  class_name: string;
  subject: string;
  teacher: string;
}

export interface ScheduleByClass {
  classes: string[];
  grid: Record<string, Record<number, Record<number, ScheduleCell | null>>>;
  obj_value: number;
  metrics: Record<string, number>;
}

export interface ScheduleByTeacher {
  teachers: string[];
  grid: Record<
    string,
    Record<number, Record<number, ScheduleTeacherCell | null>>
  >;
}

export interface ScheduleByRoom {
  rooms: string[];
  rooms_meta: Record<string, { kind: RoomKind; capacity: number }>;
  grid: Record<string, Record<number, Record<number, ScheduleRoomCell[]>>>;
}

// ============================================================
// Optimisation runs + log entries
// ============================================================

export interface RunSummary {
  id: number;
  kind: string;
  name: string;
  profile?: string | null;
  status: "pending" | "running" | "done" | "failed" | string;
  progress: number;
  obj_value?: number | null;
  metrics: Record<string, number | string>;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  solution_id?: number | null;
}

// ============================================================
// Dataset / mock generation
// ============================================================

export interface DatasetState {
  classes: number;
  teachers: number;
  subjects: number;
  assignments: number;
  classrooms: number;
  solutions: number;
  curricula: number;
  students: number;
  groups: number;
  active_solution?: {
    id: number;
    name: string;
    kind: string;
    obj_value: number;
    metrics: Record<string, number | string>;
  } | null;
}

// ============================================================
// API helpers
// ============================================================

/** Canonical error response from the backend (Section 2.3 P2). */
export interface ApiErrorResponse {
  detail: string;
  code?: string;
  errors?: Array<{ msg: string; field?: string | null; type?: string | null }>;
  hint?: string | null;
  request_id?: string | null;
  /** Legacy alias kept for backwards compatibility */
  error?: string;
}

/** Pagination envelope returned when ?limit or ?offset is set. */
export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number | null;
  offset: number;
}
