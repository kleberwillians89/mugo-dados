// @vitest-environment jsdom
import {act} from "react";
import {createRoot} from "react-dom/client";
import {expect,it,vi} from "vitest";
import Modal from "./Modal";
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
it("modal prende Tab, fecha por Escape e restaura foco e scroll",async()=>{
 const host=document.createElement("div"),trigger=document.createElement("button");document.body.append(host,trigger);trigger.focus();const root=createRoot(host),close=vi.fn(),overflow=document.body.style.overflow;
 try {
 await act(async()=>root.render(<Modal open title="Edição" onClose={close}><label>Nome<input/></label><button>Salvar</button></Modal>));
 expect(document.activeElement).toBe(host.querySelector(".modalClose"));
 const input=host.querySelector("input")!;input.focus();
 await act(async()=>root.render(<Modal open title="Edição" onClose={()=>close()}><label>Nome<input/></label><button>Salvar</button></Modal>));expect(document.activeElement).toBe(input);
 const buttons=host.querySelectorAll("button");const first=buttons[0],last=buttons[buttons.length-1];expect(document.activeElement).toBe(input);expect(document.body.style.overflow).toBe("hidden");
 last.focus();await act(async()=>last.dispatchEvent(new KeyboardEvent("keydown",{key:"Tab",bubbles:true,cancelable:true})));expect(document.activeElement).toBe(first);
 await act(async()=>first.dispatchEvent(new KeyboardEvent("keydown",{key:"Tab",shiftKey:true,bubbles:true,cancelable:true})));expect(document.activeElement).toBe(last);
 await act(async()=>window.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true})));expect(close).toHaveBeenCalledTimes(1);
 await act(async()=>root.render(<Modal open={false} title="Edição" onClose={close}>Fechado</Modal>));expect(document.activeElement).toBe(trigger);expect(document.body.style.overflow).toBe(overflow);
 } finally {await act(async()=>root.unmount());host.remove();trigger.remove();document.body.style.overflow=overflow;}
});
