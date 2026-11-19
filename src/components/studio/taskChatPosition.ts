/** Viewport-safe position for the floating task inbox. No tenant data is stored. */
export type TaskChatPosition = { x: number; y: number };
export const TASK_CHAT_STORAGE_KEY = "mugo.global-task-chat.position.v1";
const PAD = 12;

export function clampTaskChatPosition(pos: TaskChatPosition, width: number, height: number, triggerWidth: number, triggerHeight: number): TaskChatPosition {
  const maxX = Math.max(0, width - Math.max(1, triggerWidth) - PAD);
  const maxY = Math.max(0, height - Math.max(1, triggerHeight) - PAD);
  return {
    x: Math.min(maxX, Math.max(0, Number.isFinite(pos.x) ? pos.x : 0)),
    y: Math.min(maxY, Math.max(0, Number.isFinite(pos.y) ? pos.y : 0)),
  };
}

export function defaultTaskChatPosition(width: number, height: number, triggerWidth: number, triggerHeight: number): TaskChatPosition {
  return clampTaskChatPosition({x: width - triggerWidth - 20, y: height - triggerHeight - 20}, width, height, triggerWidth, triggerHeight);
}

export function taskChatPanelGeometry(
  pos: TaskChatPosition, viewportWidth: number, viewportHeight: number, triggerWidth: number, triggerHeight: number,
) {
  const margin = 12, gap = 9;
  const width = Math.min(420, Math.max(140, viewportWidth - margin * 2));
  const above = Math.max(0, pos.y - gap - margin);
  const below = Math.max(0, viewportHeight - pos.y - triggerHeight - gap - margin);
  const opensBelow = below > above;
  const leftAbsolute = Math.min(Math.max(margin, pos.x + triggerWidth - width), Math.max(margin, viewportWidth - margin - width));
  return {
    left: leftAbsolute - pos.x,
    top: opensBelow ? triggerHeight + gap : "auto",
    bottom: opensBelow ? "auto" : triggerHeight + gap,
    maxHeight: Math.max(0, Math.min(620, opensBelow ? below : above)),
    width,
  };
}
