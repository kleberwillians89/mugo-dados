// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { vi, test, expect } from "vitest";
import Ecommerce from "./Ecommerce";
vi.mock("../app/DashboardDataContext",()=>({useDashboardSnapshot:()=>({sources:[{provider:"shopify"}]})}));
vi.mock("./Shopify",()=>({default:()=> <div>Shopify direto</div>}));
test("abre ecommerce pelo snapshot sem request de connections",async()=>{const node=document.createElement("div"),root=createRoot(node);await act(async()=>root.render(<Ecommerce isAuthenticated onLogout={vi.fn()} onOpenDashboard={vi.fn()} onOpenGoogleReport={vi.fn()}/>));expect(node.textContent).toContain("Shopify direto");act(()=>root.unmount());});
