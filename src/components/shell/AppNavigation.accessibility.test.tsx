// @vitest-environment jsdom
import {act} from "react";
import {createRoot} from "react-dom/client";
import {expect,it,vi} from "vitest";
import AppNavigation from "./AppNavigation";
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
it("gaveta contém o foco por Tab e restaura o scroll anterior ao fechar",async()=>{
 const node=document.createElement("div");document.body.append(node);const root=createRoot(node);
 const old=document.body.style.overflow;document.body.style.overflow="clip";
 try {
 await act(async()=>root.render(<AppNavigation route="meta" platformAdmin={false} agencyAdmin={false} canManageIntegrations={false} onOpen={vi.fn()} onLogout={vi.fn()} clients={[{client_id:"fixture",name:"Empresa fictícia",role:"viewer"}]} activeClientId="fixture"/>));
 const open=node.querySelector<HTMLButtonElement>('.appTopbarMenu')!;await act(async()=>open.click());expect(document.body.style.overflow).toBe("hidden");
 const focusable=[...node.querySelectorAll<HTMLElement>('.appSidebar a[href], .appSidebar button:not(:disabled), .appSidebar input:not(:disabled)')];
 const first=focusable[0],last=focusable[focusable.length-1];last.focus();await act(async()=>last.dispatchEvent(new KeyboardEvent("keydown",{key:"Tab",bubbles:true,cancelable:true})));expect(document.activeElement).toBe(first);
 await act(async()=>first.dispatchEvent(new KeyboardEvent("keydown",{key:"Tab",shiftKey:true,bubbles:true,cancelable:true})));expect(document.activeElement).toBe(last);
 await act(async()=>document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true})));expect(document.body.style.overflow).toBe("clip");expect(document.activeElement).toBe(open);
 } finally {await act(async()=>root.unmount());node.remove();document.body.style.overflow=old;}
});
