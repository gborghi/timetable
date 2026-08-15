/**
 * Schedule validation logic extracted from WeeklyCalendarView.svelte.
 * 
 * Pure functions for conflict detection, drop validation, and
 * schedule constraint checking. No Svelte dependencies.
 */

/**
 * Represents a lesson in the schedule.
 */
export interface Lesson {
  id: number | string;
  teacher_name?: string;
  class_name?: string;
  classroom_name?: string;
  day?: number;
  hour?: number;
  subject?: string;
  [key: string]: any;
}

/**
 * Represents an unscheduled pool entry.
 */
export interface UnscheduledEntry {
  id: number | string;
  teacher_name?: string;
  class_name?: string;
  classroom_name?: string;
  [key: string]: any;
}

/**
 * Drag source type for schedule mode.
 */
export type DragSource = 
  | { kind: 'lesson'; lesson: Lesson }
  | { kind: 'unscheduled'; entry: UnscheduledEntry }
  | null;

/**
 * Calculate which slot keys would have HARD conflicts if the dragged
 * lesson were dropped there.
 * 
 * A conflict occurs when:
 * - Same teacher is busy at that slot (different lesson)
 * - Same class is busy at that slot (different lesson)
 * - Same classroom is busy at that slot (different lesson)
 * 
 * @param dragSource - The lesson or unscheduled entry being dragged
 * @param allLessons - All lessons in the schedule (full array, not filtered)
 * @param excludeLessonId - ID of the dragged lesson itself (to exclude from conflict check)
 * @returns Set of "day-hour" keys that would conflict
 */
export function calculateConflictKeys(
  dragSource: DragSource,
  allLessons: Lesson[],
  excludeLessonId?: number | string
): Set<string> {
  if (!dragSource) return new Set();
  
  const drag = dragSource.kind === 'lesson'
    ? dragSource.lesson
    : dragSource.entry;
  
  if (!drag) return new Set();
  
  const conflictKeys = new Set<string>();
  
  for (const l of allLessons) {
    // Skip the dragged lesson itself
    if (excludeLessonId !== undefined && l.id === excludeLessonId) continue;
    
    // Check if this lesson conflicts with the dragged one
    if (
      (drag.teacher_name && l.teacher_name === drag.teacher_name) ||
      (drag.class_name && l.class_name === drag.class_name) ||
      (drag.classroom_name && drag.classroom_name === l.classroom_name)
    ) {
      // This lesson shares a resource with the dragged one
      // Mark its slot as a conflict
      if (l.day !== undefined && l.hour !== undefined) {
        conflictKeys.add(`${l.day}-${l.hour}`);
      }
    }
  }
  
  return conflictKeys;
}

/**
 * Check if a drop target is valid (configured slot exists).
 * 
 * @param day - Day number (1-7)
 * @param hour - Hour number (0-23)
 * @param configuredSlots - Set of "day-hour" keys for configured slots
 * @returns true if the slot is configured and accepts drops
 */
export function isValidDropTarget(
  day: number,
  hour: number,
  configuredSlots: Set<string>
): boolean {
  const key = `${day}-${hour}`;
  return configuredSlots.has(key);
}

/**
 * Check if moving a lesson to a new slot would create a conflict.
 * 
 * @param lesson - The lesson being moved
 * @param newDay - Target day
 * @param newHour - Target hour
 * @param allLessons - All lessons in the schedule
 * @returns true if the move would create a conflict
 */
export function wouldCreateConflict(
  lesson: Lesson,
  newDay: number,
  newHour: number,
  allLessons: Lesson[]
): boolean {
  for (const l of allLessons) {
    if (l.id === lesson.id) continue; // Skip self
    if (l.day !== newDay || l.hour !== newHour) continue; // Different slot
    
    // Same slot - check for resource conflicts
    if (
      (lesson.teacher_name && l.teacher_name === lesson.teacher_name) ||
      (lesson.class_name && l.class_name === lesson.class_name) ||
      (lesson.classroom_name && l.classroom_name === lesson.classroom_name)
    ) {
      return true;
    }
  }
  
  return false;
}

/**
 * Find all conflicts in the current schedule.
 * 
 * @param lessons - All lessons in the schedule
 * @returns Array of conflict pairs [{lesson1, lesson2, reason}]
 */
export function findAllConflicts(
  lessons: Lesson[]
): Array<{ lesson1: Lesson; lesson2: Lesson; reason: string }> {
  const conflicts: Array<{ lesson1: Lesson; lesson2: Lesson; reason: string }> = [];
  
  for (let i = 0; i < lessons.length; i++) {
    for (let j = i + 1; j < lessons.length; j++) {
      const l1 = lessons[i];
      const l2 = lessons[j];
      
      // Same slot?
      if (l1.day === l2.day && l1.hour === l2.hour) {
        // Check for resource conflicts
        if (l1.teacher_name && l2.teacher_name && l1.teacher_name === l2.teacher_name) {
          conflicts.push({
            lesson1: l1,
            lesson2: l2,
            reason: `Stesso docente (${l1.teacher_name}) nello stesso slot`
          });
        }
        if (l1.class_name && l2.class_name && l1.class_name === l2.class_name) {
          conflicts.push({
            lesson1: l1,
            lesson2: l2,
            reason: `Stessa classe (${l1.class_name}) nello stesso slot`
          });
        }
        if (l1.classroom_name && l2.classroom_name && l1.classroom_name === l2.classroom_name) {
          conflicts.push({
            lesson1: l1,
            lesson2: l2,
            reason: `Stessa aula (${l1.classroom_name}) nello stesso slot`
          });
        }
      }
    }
  }
  
  return conflicts;
}

/**
 * Validate that a schedule has no conflicts.
 * 
 * @param lessons - All lessons in the schedule
 * @returns {valid: boolean, conflicts: Array}
 */
export function validateSchedule(
  lessons: Lesson[]
): { valid: boolean; conflicts: Array<{ lesson1: Lesson; lesson2: Lesson; reason: string }> } {
  const conflicts = findAllConflicts(lessons);
  return {
    valid: conflicts.length === 0,
    conflicts
  };
}
