/**
 * TanStack Query hooks per resource.
 *
 * Each list-resource gets:
 *   keys: object of stable query-key tuples (so invalidate() is type-safe)
 *   useList()           -- createQuery wrapping services.<r>.list()
 *   useCreate/Update/Remove -- createMutation wrappers that invalidate
 *                              the list key on success
 *
 * Use from a component:
 *
 *   <script lang="ts">
 *     import { teachersQuery } from '$lib/queries';
 *     const list = teachersQuery.useList();
 *     // $list.data, $list.isLoading, $list.error
 *   </script>
 *
 * Section 1.2 P2 of docs/improvements.md.
 */

import { createQuery, createMutation, useQueryClient } from "@tanstack/svelte-query";
import {
  classes as classesSvc,
  classrooms as classroomsSvc,
  coteaching as coteachingSvc,
  curricula as curriculaSvc,
  dataset as datasetSvc,
  groups as groupsSvc,
  students as studentsSvc,
  subjects as subjectsSvc,
  teachers as teachersSvc,
} from "../services";
import type {
  Classroom,
  CoteachingRule,
  Curriculum,
  DatasetState,
  SchoolClass,
  Student,
  StudyGroup,
  Subject,
  Teacher,
} from "../types";

// ============================================================
// Teachers
// ============================================================

export const teachersQuery = {
  keys: { all: ["teachers"] as const },

  useList() {
    return createQuery<Teacher[]>(() => ({
      queryKey: teachersQuery.keys.all,
      queryFn: () => teachersSvc.list(),
    }));
  },

  useCreate() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: (b: Partial<Teacher>) => teachersSvc.create(b),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: teachersQuery.keys.all }),
    }));
  },

  useUpdate() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: ({ id, body }: { id: number; body: Partial<Teacher> }) =>
        teachersSvc.update(id, body),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: teachersQuery.keys.all }),
    }));
  },

  useRemove() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: (id: number) => teachersSvc.remove(id),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: teachersQuery.keys.all }),
    }));
  },
};

// ============================================================
// Classes
// ============================================================

export const classesQuery = {
  keys: { all: ["classes"] as const },

  useList() {
    return createQuery<SchoolClass[]>(() => ({
      queryKey: classesQuery.keys.all,
      queryFn: () => classesSvc.list(),
    }));
  },

  useCreate() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: (b: Partial<SchoolClass>) => classesSvc.create(b),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: classesQuery.keys.all }),
    }));
  },

  useUpdate() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: ({
        id,
        body,
      }: {
        id: number;
        body: Partial<SchoolClass>;
      }) => classesSvc.update(id, body),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: classesQuery.keys.all }),
    }));
  },

  useRemove() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: (id: number) => classesSvc.remove(id),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: classesQuery.keys.all }),
    }));
  },
};

// ============================================================
// Subjects
// ============================================================

export const subjectsQuery = {
  keys: {
    all: ["subjects"] as const,
    weights: ["subjects", "group-weights"] as const,
  },

  useList() {
    return createQuery<Subject[]>(() => ({
      queryKey: subjectsQuery.keys.all,
      queryFn: () => subjectsSvc.list(),
    }));
  },

  useGroupWeights() {
    return createQuery(() => ({
      queryKey: subjectsQuery.keys.weights,
      queryFn: () => subjectsSvc.groupWeights(),
    }));
  },

  useCreate() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: (b: Partial<Subject>) => subjectsSvc.create(b),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: subjectsQuery.keys.all }),
    }));
  },

  useUpdate() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: ({ id, body }: { id: number; body: Partial<Subject> }) =>
        subjectsSvc.update(id, body),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: subjectsQuery.keys.all }),
    }));
  },

  useRemove() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: (id: number) => subjectsSvc.remove(id),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: subjectsQuery.keys.all }),
    }));
  },
};

// ============================================================
// Classrooms
// ============================================================

export const classroomsQuery = {
  keys: { all: ["classrooms"] as const },

  useList() {
    return createQuery<Classroom[]>(() => ({
      queryKey: classroomsQuery.keys.all,
      queryFn: () => classroomsSvc.list(),
    }));
  },

  useCreate() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: (b: Partial<Classroom>) => classroomsSvc.create(b),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: classroomsQuery.keys.all }),
    }));
  },

  useUpdate() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: ({ id, body }: { id: number; body: Partial<Classroom> }) =>
        classroomsSvc.update(id, body),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: classroomsQuery.keys.all }),
    }));
  },

  useRemove() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: (id: number) => classroomsSvc.remove(id),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: classroomsQuery.keys.all }),
    }));
  },
};

// ============================================================
// Students
// ============================================================

export const studentsQuery = {
  keys: { all: ["students"] as const },

  useList() {
    return createQuery<Student[]>(() => ({
      queryKey: studentsQuery.keys.all,
      queryFn: () => studentsSvc.list(),
    }));
  },

  useCreate() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: (b: Partial<Student>) => studentsSvc.create(b),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: studentsQuery.keys.all }),
    }));
  },

  useUpdate() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: ({ id, body }: { id: number; body: Partial<Student> }) =>
        studentsSvc.update(id, body),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: studentsQuery.keys.all }),
    }));
  },

  useRemove() {
    const qc = useQueryClient();
    return createMutation(() => ({
      mutationFn: (id: number) => studentsSvc.remove(id),
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: studentsQuery.keys.all }),
    }));
  },
};

// ============================================================
// Curricula
// ============================================================

export const curriculaQuery = {
  keys: { all: ["curricula"] as const },

  useList() {
    return createQuery<Curriculum[]>(() => ({
      queryKey: curriculaQuery.keys.all,
      queryFn: () => curriculaSvc.list(),
    }));
  },
};

// ============================================================
// Groups
// ============================================================

export const groupsQuery = {
  keys: { all: ["groups"] as const },

  useList() {
    return createQuery<StudyGroup[]>(() => ({
      queryKey: groupsQuery.keys.all,
      queryFn: () => groupsSvc.list(),
    }));
  },
};

// ============================================================
// Coteaching
// ============================================================

export const coteachingQuery = {
  keys: { all: ["coteaching"] as const },

  useList() {
    return createQuery<CoteachingRule[]>(() => ({
      queryKey: coteachingQuery.keys.all,
      queryFn: () => coteachingSvc.list(),
    }));
  },
};

// ============================================================
// Dataset state (cached very actively -- header pills poll it)
// ============================================================

export const datasetQuery = {
  keys: { state: ["dataset", "state"] as const },

  useState() {
    return createQuery<DatasetState>(() => ({
      queryKey: datasetQuery.keys.state,
      queryFn: () => datasetSvc.state(),
      // Backend caches this for 30s; double up here so both layers
      // collaborate.
      staleTime: 15_000,
    }));
  },
};
