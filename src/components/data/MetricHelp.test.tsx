// @vitest-environment jsdom
import {act} from "react";
import {createRoot, type Root} from "react-dom/client";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import MetricHelp from "./MetricHelp";
import KpiCard from "../KpiCard";
import {METRIC_GLOSSARY, metricIdForLabel} from "../../app/metricGlossary";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, node: HTMLDivElement;
beforeEach(() => {node=document.createElement("div");document.body.append(node);root=createRoot(node);});
afterEach(async()=>{await act(async()=>root.unmount());node.remove();vi.restoreAllMocks();});
it("foco explica fórmula, unidade e ressalva; Escape fecha sem perder o foco", async()=>{
 await act(async()=>root.render(<MetricHelp label="CPC"/>));const button=node.querySelector("button")!;
 await act(async()=>button.focus());const tip=document.querySelector('[role="tooltip"]')!;
 expect(tip.textContent).toContain("Investimento / cliques");expect(tip.textContent).toContain("R$/clique");expect(tip.textContent).toContain("Google Ads");
 expect(button.getAttribute("aria-describedby")).toBe(tip.id);
 await act(async()=>document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true})));
 expect(document.querySelector('[role="tooltip"]')).toBeNull();expect(document.activeElement).toBe(button);
});
it("toque alterna e toque fora fecha sem selecionar o card", async()=>{
 const select=vi.fn();await act(async()=>root.render(<KpiCard label="Alcance" value="10" onClick={select}/>));
 const help=node.querySelector('[aria-label="Entender Alcance"]') as HTMLButtonElement;
 const tap=()=>{help.dispatchEvent(new MouseEvent("pointerdown",{bubbles:true}));help.dispatchEvent(new MouseEvent("click",{bubbles:true,detail:1}));};
 await act(async()=>tap());expect(document.querySelector('[role="tooltip"]')).not.toBeNull();expect(select).not.toHaveBeenCalled();
 await act(async()=>tap());expect(document.querySelector('[role="tooltip"]')).toBeNull();
 await act(async()=>tap());await act(async()=>document.body.dispatchEvent(new MouseEvent("pointerdown",{bubbles:true})));expect(document.querySelector('[role="tooltip"]')).toBeNull();
 await act(async()=>(node.querySelector('[aria-label="Selecionar Alcance"]') as HTMLButtonElement).click());expect(select).toHaveBeenCalledTimes(1);
});
it("popover usa medidas reais para caber na viewport estreita", async()=>{
 const w=window.innerWidth,h=window.innerHeight;
 Object.defineProperty(window,"innerWidth",{configurable:true,value:320});Object.defineProperty(window,"innerHeight",{configurable:true,value:640});
 vi.spyOn(HTMLElement.prototype,"getBoundingClientRect").mockImplementation(function(this:HTMLElement){return {left:310,bottom:600,top:570,right:338,width:this.classList.contains("metricHelpPanel")?296:28,height:this.classList.contains("metricHelpPanel")?220:28,x:310,y:570,toJSON(){return {};}};});
 try {await act(async()=>root.render(<MetricHelp label="ROAS"/>));await act(async()=>node.querySelector("button")!.focus());
 const tip=document.querySelector<HTMLElement>('[role="tooltip"]')!;expect(parseFloat(tip.style.left)).toBeGreaterThanOrEqual(8);expect(parseFloat(tip.style.left)+296).toBeLessThanOrEqual(320);expect(parseFloat(tip.style.top)+220).toBeLessThanOrEqual(640);
 } finally {Object.defineProperty(window,"innerWidth",{configurable:true,value:w});Object.defineProperty(window,"innerHeight",{configurable:true,value:h});}
});
it("registro distingue metodologia, CTA e termos desconhecidos", async()=>{
 expect(METRIC_GLOSSARY.blendedReturn.formula).toContain("Receita da loja");expect(METRIC_GLOSSARY.purchasePerView.formula).toContain("eventos view_item");
 expect(METRIC_GLOSSARY.roas.caveat).toContain("Não representa lucro");expect(METRIC_GLOSSARY.cta.unit).toContain("Não é métrica numérica");expect(METRIC_GLOSSARY.users.caveat).toContain("soma de usuários diários");
 for(const definition of Object.values(METRIC_GLOSSARY)){expect(definition.name).toBeTruthy();expect(definition.explanation).toBeTruthy();expect(definition.unit).toBeTruthy();expect(definition.platforms).toBeTruthy();expect(definition.caveat).toBeTruthy();}
 expect(metricIdForLabel("métrica inexistente")).toBeUndefined();await act(async()=>root.render(<MetricHelp label="métrica inexistente"/>));expect(node.querySelector("button")).toBeNull();
});
