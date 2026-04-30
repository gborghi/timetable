/**
 * Services layer: per-resource thin facades over $lib/api.js.
 *
 * Pages used to embed magic URL strings ("/api/teachers", etc.). With
 * 99 such occurrences across 20 files, renaming a backend route means
 * a multi-file find/replace. The services below give each resource
 * one place to change.
 *
 * Naming convention:
 *   list()         -> GET /api/<resource>
 *   get(id)        -> GET /api/<resource>/:id  (where applicable)
 *   create(body)   -> POST /api/<resource>
 *   update(id, b)  -> PUT /api/<resource>/:id
 *   remove(id)     -> DELETE /api/<resource>/:id
 *
 * Domain-specific endpoints get verbose names (e.g. coverageWeek,
 * suggestedCounts, autoGenerate) so the call sites read naturally.
 *
 * The services are thin on purpose: NO error handling, NO logging,
 * NO caching. Cross-cutting concerns belong in api.js / stores.js.
 */

import { api } from '$lib/api.js';

// ---------------- Teachers ----------------

export const teachers = {
  list:   ()           => api.get('/api/teachers'),
  create: (b)          => api.post('/api/teachers', b),
  update: (id, b)      => api.put('/api/teachers/' + id, b),
  remove: (id)         => api.del('/api/teachers/' + id),
};

// ---------------- Classes -----------------

export const classes = {
  list:   ()           => api.get('/api/classes'),
  create: (b)          => api.post('/api/classes', b),
  update: (id, b)      => api.put('/api/classes/' + id, b),
  remove: (id)         => api.del('/api/classes/' + id),
};

// ---------------- Subjects ----------------

export const subjects = {
  list:           ()      => api.get('/api/subjects'),
  create:         (b)     => api.post('/api/subjects', b),
  update:         (id, b) => api.put('/api/subjects/' + id, b),
  remove:         (id)    => api.del('/api/subjects/' + id),
  groupWeights:   ()      => api.get('/api/subjects/group-weights'),
  setGroupWeights:(w)     => api.put('/api/subjects/group-weights', w),
};

// ---------------- Classrooms --------------

export const classrooms = {
  list:             ()      => api.get('/api/classrooms'),
  create:           (b)     => api.post('/api/classrooms', b),
  update:           (id, b) => api.put('/api/classrooms/' + id, b),
  remove:           (id)    => api.del('/api/classrooms/' + id),
  suggestedCounts:  ()      => api.get('/api/classrooms/suggested-counts'),
  autoGenerate:     (b={})  => api.post('/api/classrooms/auto-generate', b),
};

// ---------------- Students ----------------

export const students = {
  list:   ()      => api.get('/api/students'),
  create: (b)     => api.post('/api/students', b),
  update: (id, b) => api.put('/api/students/' + id, b),
  remove: (id)    => api.del('/api/students/' + id),
};

// ---------------- Groups ------------------

export const groups = {
  list:   ()      => api.get('/api/groups'),
  create: (b)     => api.post('/api/groups', b),
  update: (id, b) => api.put('/api/groups/' + id, b),
  remove: (id)    => api.del('/api/groups/' + id),
};

// ---------------- Curricula ---------------

export const curricula = {
  list:   ()      => api.get('/api/curricula'),
  create: (b)     => api.post('/api/curricula', b),
  update: (id, b) => api.put('/api/curricula/' + id, b),
  remove: (id)    => api.del('/api/curricula/' + id),
};

// ---------------- Coteaching --------------

export const coteaching = {
  list:   ()      => api.get('/api/coteaching'),
  create: (b)     => api.post('/api/coteaching', b),
  update: (id, b) => api.put('/api/coteaching/' + id, b),
  remove: (id)    => api.del('/api/coteaching/' + id),
};

// ---------------- Dataset / mock ----------

export const dataset = {
  state:             ()      => api.get('/api/dataset/state'),
  availableProfiles: ()      => api.get('/api/dataset/available-profiles'),
  importProfile:     (b)     => api.post('/api/dataset/import-profile', b),
  mock:              (b)     => api.post('/api/dataset/mock', b),
  clear:             (scope='all') => api.post('/api/dataset/clear?scope=' + encodeURIComponent(scope)),
};

// ---------------- Schedule ----------------

export const schedule = {
  byClass:        ()      => api.get('/api/schedule/by-class'),
  byTeacher:      ()      => api.get('/api/schedule/by-teacher'),
  byRoom:         ()      => api.get('/api/schedule/by-room'),
  solutions:      ()      => api.get('/api/schedule/solutions'),
  activateSolution:(id)   => api.post('/api/schedule/solutions/' + id + '/activate'),
  removeSolution:  (id)   => api.del('/api/schedule/solutions/' + id),
  moveLesson:     (b)     => api.put('/api/schedule/move-lesson', b),
  movePreview:    (b)     => api.post('/api/schedule/move-preview', b),
  setLessonClassroom: (lessonId, classroom, opts='') =>
    api.put('/api/schedule/lesson/' + lessonId + '/classroom' + opts, { classroom }),
  exportUrl: (kind /* 'xlsx-classes'|'xlsx-teachers'|'pdf-classes'|'pdf-teachers' */) =>
    '/api/schedule/export/' + kind,
};

// ---------------- Monitor -----------------

export const monitor = {
  summary:        ()      => api.get('/api/monitor/summary'),
  conflicts:      ()      => api.get('/api/monitor/conflicts'),
  eventLessons:   (eventId)        => api.get('/api/monitor/event/' + eventId + '/lessons'),
  updateLesson:   (eventId, lid, b) => api.put(
                          '/api/monitor/event/' + eventId + '/lesson/' + lid, b),
};

// ---------------- Assignments -------------

export const assignments = {
  byClass:           ()              => api.get('/api/assignments/by-class'),
  loads:             ()              => api.get('/api/assignments/loads'),
  teachersForSubject:(subject)       => api.get(
                              '/api/assignments/teachers-for-subject?subject='
                              + encodeURIComponent(subject)),
  manual:            (b)             => api.put('/api/assignments/manual', b),
  setLock:           (id, locked)    => api.post(
                              '/api/assignments/lock/' + id + '?locked=' + (locked ? 'true' : 'false')),
};

// ---------------- Coverage / absences -----

export const coverage = {
  week:               (weekStart)    => api.get('/api/coverage/week?week_start='
                                                + encodeURIComponent(weekStart)),
  createAbsence:      (b)            => api.post('/api/absences', b),
  removeAbsenceById:  (id)           => api.del('/api/absences/by-id/' + id),
  removeAbsencesOnDate:(date)        => api.del('/api/absences?date=' + encodeURIComponent(date)),
  createSubstitution: (b)            => api.post('/api/substitutions', b),
  removeSubstitution: (id)           => api.del('/api/substitutions/' + id),
};

// ---------------- Optimize ----------------

export const optimize = {
  runs:        (limit=15) => api.get('/api/optimize/runs?limit=' + limit),
  // The optimize page builds its own URL list -> expose them as constants
  // so renaming the backend stays a one-line edit.
  endpoints: {
    mock:           '/api/dataset/mock',
    importProfile:  '/api/dataset/import-profile',
    assignment:     '/api/optimize/assignment',
    phaseB:         '/api/optimize/phase-b',
    metaPrefix:     '/api/optimize/meta/',  // append <stage>
    rooms:          '/api/optimize/rooms',
    fullPipeline:   '/api/optimize/full-pipeline',
  },
};

// ---------------- Logic / DSL -------------

export const logic = {
  validate: (expression) => api.post('/api/logic/validate', { expression }),
};
