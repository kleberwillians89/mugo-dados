import { describe, expect, it } from "vitest";
import { clampTaskChatPosition, defaultTaskChatPosition, taskChatPanelGeometry } from "./taskChatPosition";

describe("Chat de tarefas flutuante", () => {
  it("starts at lower right but remains inside screen", () => {
    const pos = defaultTaskChatPosition(1200, 800, 174, 48);
    expect(pos).toEqual({x:1006,y:732});
  });

  it("clamps dragging beyond every edge", () => {
    expect(clampTaskChatPosition({x:-100,y:-50}, 390, 844, 180, 48)).toEqual({x:0,y:0});
    expect(clampTaskChatPosition({x:9999,y:9999}, 390, 844, 180, 48)).toEqual({x:198,y:784});
  });

  it("keeps saved locations in view when viewport shrinks", () => {
    expect(clampTaskChatPosition({x:1000,y:740}, 320, 640, 180, 48)).toEqual({x:128,y:580});
  });

  it("opens the task list on screen without stealing modal footer", () => {
    const right = taskChatPanelGeometry({x:1000,y:720},1200,800,174,48);
    expect(right.bottom).toBe(57);
    expect(right.top).toBe("auto");
    expect(right.maxHeight).toBeGreaterThan(500);
    expect(right.left).toBeLessThan(0);
    const upperLeft = taskChatPanelGeometry({x:8,y:16},390,844,174,48);
    expect(upperLeft.top).toBe(57);
    expect(upperLeft.bottom).toBe("auto");
    expect(upperLeft.left).toBeGreaterThanOrEqual(0);
    expect(upperLeft.width).toBeLessThanOrEqual(390);
  });
});
