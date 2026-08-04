/**
 * Services layer: per-resource thin facades over $lib/api.ts.
 *
 * Each resource exposes the standard CRUD verbs:
 *   list(), create(body), update(id, body), remove(id)
 * Plus domain-specific verbs where useful (e.g. classrooms.suggestedCounts,
 * subjects.groupWeights, schedule.byClass, ...).
 *
 * The services are thin on purpose: NO error handling, NO logging,
 * NO caching. Cross-cutting concerns belong in api.ts / stores.ts and
 * (now) the TanStack Query layer in `$lib/queries`.
 */

import { api } from "../api";
import type {
  Assignment,
  Classroom,
  ClassroomTag,
  Curriculum,
  CoteachingRule,
  DatasetState,
  SchoolClass,
  Solution,
  Student,
  StudentTag,
  StudyGroup,
  Subject,
  SubjectGroupWeight,
  Teacher,
} from "../types";

// ---------------- Teachers ----------------

export const teachers = {
  list: () => api.get<Teacher[]>("/api/teachers"),
  create: (b: Partial<Teacher>) => api.post<Teacher>("/api/teachers", b),
  update: (id: number, b: Partial<Teacher>) =>
    api.put<Teacher>("/api/teachers/" + id, b),
  remove: (id: number) => api.del<void>("/api/teachers/" + id),
};

// ---------------- Classes -----------------

export const classes = {
  list: () => api.get<SchoolClass[]>("/api/classes"),
  create: (b: Partial<SchoolClass>) => api.post<SchoolClass>("/api/classes", b),
  update: (id: number, b: Partial<SchoolClass>) => {
    // Heuristic: a small partial body (single inline-edit field) goes
    // via PATCH; a full SchoolClass replaces via PUT. The PATCH route
    // whitelists the inline-editable columns server-side, so this
    // chooses the right verb without callers having to remember.
    const keys = Object.keys(b ?? {});
    const PATCH_KEYS = new Set([
      "n_students", "max_hours_per_day", "required_free_days_count",
      "notes", "nickname", "soft_minimize_sixth_weight", "room_policy",
    ]);
    if (keys.length > 0 && keys.every((k) => PATCH_KEYS.has(k))) {
      return api.patch<SchoolClass>("/api/classes/" + id, b);
    }
    return api.put<SchoolClass>("/api/classes/" + id, b);
  },
  remove: (id: number) => api.del<void>("/api/classes/" + id),
};

// ---------------- Subjects ----------------

export const subjects = {
  list: () => api.get<Subject[]>("/api/subjects"),
  create: (b: Partial<Subject>) => api.post<Subject>("/api/subjects", b),
  update: (id: number, b: Partial<Subject>) =>
    api.put<Subject>("/api/subjects/" + id, b),
  remove: (id: number) => api.del<void>("/api/subjects/" + id),
  groupWeights: () =>
    api.get<SubjectGroupWeight[]>("/api/subjects/group-weights"),
  setGroupWeights: (w: SubjectGroupWeight[]) =>
    api.put<SubjectGroupWeight[]>("/api/subjects/group-weights", w),
};

// ---------------- Classrooms --------------

export const classrooms = {
  list: () => api.get<Classroom[]>("/api/classrooms"),
  create: (b: Partial<Classroom>) =>
    api.post<Classroom>("/api/classrooms", b),
  update: (id: number, b: Partial<Classroom>) => {
    // Same PATCH-vs-PUT heuristic as `classes.update`: a body that
    // touches only inline-editable columns goes via PATCH, otherwise
    // the full-replace PUT path runs.
    const keys = Object.keys(b ?? {});
    const PATCH_KEYS = new Set([
      "capacity", "kind", "notes", "multi_class",
      "multi_class_max", "multi_class_pref",
      "multi_class_pref_weight", "plesso_id",
    ]);
    if (keys.length > 0 && keys.every((k) => PATCH_KEYS.has(k))) {
      return api.patch<Classroom>("/api/classrooms/" + id, b);
    }
    return api.put<Classroom>("/api/classrooms/" + id, b);
  },
  remove: (id: number) => api.del<void>("/api/classrooms/" + id),
  suggestedCounts: () =>
    api.get<{ counts: Record<string, number>; n_classes: number }>(
      "/api/classrooms/suggested-counts",
    ),
  autoGenerate: (b: Record<string, unknown> = {}) =>
    api.post<{ created: number; n_classes: number }>(
      "/api/classrooms/auto-generate",
      b,
    ),
};

// ---------------- Classroom tags ----------

export const classroomTags = {
  list: () => api.get<ClassroomTag[]>("/api/classroom-tags"),
  create: (b: { name: string; description?: string | null }) =>
    api.post<ClassroomTag>("/api/classroom-tags", b),
  update: (
    id: number,
    b: { name?: string; description?: string | null },
  ) => api.put<ClassroomTag>("/api/classroom-tags/" + id, b),
  remove: (id: number) => api.del<void>("/api/classroom-tags/" + id),
};

// ---------------- Students ----------------

export const students = {
  list: () => api.get<Student[]>("/api/students"),
  create: (b: Partial<Student>) => api.post<Student>("/api/students", b),
  update: (id: number, b: Partial<Student>) =>
    api.put<Student>("/api/students/" + id, b),
  remove: (id: number) => api.del<void>("/api/students/" + id),
  byTags: (q: { any_of?: string[]; all_of?: string[] } = {}) => {
    const params = new URLSearchParams();
    if (q.any_of?.length) params.set("any_of", q.any_of.join(","));
    if (q.all_of?.length) params.set("all_of", q.all_of.join(","));
    return api.get<Array<Record<string, unknown>>>(
      "/api/students/by-tags" + (params.toString() ? "?" + params : ""),
    );
  },
};

// ---------------- Student tags ------------

export const studentTags = {
  list: () => api.get<StudentTag[]>("/api/student-tags"),
  create: (b: { name: string; description?: string | null }) =>
    api.post<StudentTag>("/api/student-tags", b),
  update: (
    id: number,
    b: { name?: string; description?: string | null },
  ) => api.put<StudentTag>("/api/student-tags/" + id, b),
  remove: (id: number) => api.del<void>("/api/student-tags/" + id),
};

// ---------------- Groups ------------------

export const groups = {
  list: () => api.get<StudyGroup[]>("/api/groups"),
  create: (b: Partial<StudyGroup>) =>
    api.post<StudyGroup>("/api/groups", b),
  update: (id: number, b: Partial<StudyGroup>) =>
    api.put<StudyGroup>("/api/groups/" + id, b),
  remove: (id: number) => api.del<void>("/api/groups/" + id),
};

// ---------------- Curricula ---------------

export const curricula = {
  list: () => api.get<Curriculum[]>("/api/curricula"),
  create: (b: Partial<Curriculum>) =>
    api.post<Curriculum>("/api/curricula", b),
  update: (id: number, b: Partial<Curriculum>) =>
    api.put<Curriculum>("/api/curricula/" + id, b),
  remove: (id: number) => api.del<void>("/api/curricula/" + id),
};

// ---------------- Coteaching --------------

export const coteaching = {
  list: () => api.get<CoteachingRule[]>("/api/coteaching"),
  create: (b: Partial<CoteachingRule>) =>
    api.post<CoteachingRule>("/api/coteaching", b),
  update: (id: number, b: Partial<CoteachingRule>) =>
    api.put<CoteachingRule>("/api/coteaching/" + id, b),
  remove: (id: number) => api.del<void>("/api/coteaching/" + id),
};

// ---------------- Dataset / mock ----------

export const dataset = {
  state: () => api.get<DatasetState>("/api/dataset/state"),
  availableProfiles: () =>
    api.get<{ profiles: string[] }>("/api/dataset/available-profiles"),
  importProfile: (b: Record<string, unknown>) =>
    api.post<{ run_id: number }>("/api/dataset/import-profile", b),
  mock: (b: Record<string, unknown>) =>
    api.post<{ run_id: number }>("/api/dataset/mock", b),
  clear: (scope = "all") =>
    api.post<unknown>(
      "/api/dataset/clear?scope=" + encodeURIComponent(scope),
    ),
};

// ---------------- Schedule ----------------

export const schedule = {
  byClass: () => api.get<unknown>("/api/schedule/by-class"),
  byTeacher: () => api.get<unknown>("/api/schedule/by-teacher"),
  byRoom: () => api.get<unknown>("/api/schedule/by-room"),
  solutions: () => api.get<Solution[]>("/api/schedule/solutions"),
  /** Rejects with 409 when the solution is incomplete or infeasible;
   * pass `force` to override (and tell the user what they overrode). */
  activateSolution: (id: number, force = false) =>
    api.post<unknown>("/api/schedule/solutions/" + id + "/activate"
      + (force ? "?force=true" : "")),
  solutionHealth: (id: number) =>
    api.get<unknown>("/api/schedule/solutions/" + id + "/health"),
  removeSolution: (id: number) =>
    api.del<void>("/api/schedule/solutions/" + id),
  /** No callers yet -- /schedule posts directly. If you adopt it:
   * the response may come back `{accepted: false, needs_unlock: true}`
   * when the lesson is pinned to its slot, and the correct handling is
   * to ask the user and retry with `unlock: true`, NOT to treat it as a
   * plain failure. See onLessonMove in routes/schedule/+page.svelte. */
  moveLesson: (b: Record<string, unknown>) =>
    api.put<unknown>("/api/schedule/move-lesson", b),
  movePreview: (b: Record<string, unknown>) =>
    api.post<unknown>("/api/schedule/move-preview", b),
  setLessonClassroom: (lessonId: number, classroom: string, opts = "") =>
    api.put<unknown>(
      "/api/schedule/lesson/" + lessonId + "/classroom" + opts,
      { classroom },
    ),
  exportUrl: (
    kind: "xlsx-classes" | "xlsx-teachers" | "pdf-classes" | "pdf-teachers",
  ) => "/api/schedule/export/" + kind,
};

// ---------------- Monitor -----------------

export const monitor = {
  summary: () => api.get<unknown>("/api/monitor/summary"),
  conflicts: () => api.get<unknown[]>("/api/monitor/conflicts"),
  eventLessons: (eventId: number) =>
    api.get<unknown>("/api/monitor/event/" + eventId + "/lessons"),
  /** No callers yet -- /monitor puts directly. Same caveat as
   * schedule.moveLesson: a re-time of a pinned lesson answers
   * `{ok: false, needs_unlock: true}` and must be confirmed and
   * retried with `unlock: true`. Re-rooming in place never trips it. */
  updateLesson: (
    eventId: number,
    lid: number,
    b: Record<string, unknown>,
  ) =>
    api.put<unknown>(
      "/api/monitor/event/" + eventId + "/lesson/" + lid,
      b,
    ),
};

// ---------------- Assignments -------------

export const assignments = {
  byClass: () => api.get<unknown>("/api/assignments/by-class"),
  loads: () => api.get<unknown>("/api/assignments/loads"),
  teachersForSubject: (subject: string) =>
    api.get<Assignment[]>(
      "/api/assignments/teachers-for-subject?subject=" +
        encodeURIComponent(subject),
    ),
  manual: (b: Record<string, unknown>) =>
    api.put<unknown>("/api/assignments/manual", b),
  setLock: (id: number, locked: boolean) =>
    api.post<unknown>(
      "/api/assignments/lock/" +
        id +
        "?locked=" +
        (locked ? "true" : "false"),
    ),
};

// ---------------- Coverage / absences -----

export const coverage = {
  week: (weekStart: string) =>
    api.get<unknown>(
      "/api/coverage/week?week_start=" + encodeURIComponent(weekStart),
    ),
  createAbsence: (b: Record<string, unknown>) =>
    api.post<unknown>("/api/absences", b),
  removeAbsenceById: (id: number) => api.del<void>("/api/absences/by-id/" + id),
  removeAbsencesOnDate: (date: string) =>
    api.del<void>("/api/absences?date=" + encodeURIComponent(date)),
  createSubstitution: (b: Record<string, unknown>) =>
    api.post<unknown>("/api/substitutions", b),
  removeSubstitution: (id: number) =>
    api.del<void>("/api/substitutions/" + id),
};

// ---------------- Optimize ----------------

export const optimize = {
  runs: (limit = 15) => api.get<unknown[]>("/api/optimize/runs?limit=" + limit),
  endpoints: {
    mock: "/api/dataset/mock",
    importProfile: "/api/dataset/import-profile",
    assignment: "/api/optimize/assignment",
    phaseB: "/api/optimize/phase-b",
    metaPrefix: "/api/optimize/meta/",
    rooms: "/api/optimize/rooms",
    fullPipeline: "/api/optimize/full-pipeline",
  },
};

// ---------------- Logic / DSL -------------

export const logic = {
  validate: (expression: string) =>
    api.post<{ ok: boolean; error?: string }>("/api/logic/validate", {
      expression,
    }),
};

// ---------------- Saved views -------------

export interface SavedView {
  id: number;
  entity: string;
  name: string;
  dsl_query?: string | null;
  sort_levels: Array<{ column: string; direction: "asc" | "desc" }>;
  description?: string | null;
}

export const savedViews = {
  list: (entity?: string) =>
    api.get<SavedView[]>(
      "/api/saved-views" + (entity ? "?entity=" + encodeURIComponent(entity) : ""),
    ),
  create: (b: Partial<SavedView>) =>
    api.post<SavedView>("/api/saved-views", b),
  update: (id: number, b: Partial<SavedView>) =>
    api.put<SavedView>("/api/saved-views/" + id, b),
  remove: (id: number) => api.del<void>("/api/saved-views/" + id),
};
