"""Regras alteradas nesta rodada; mutações somente em cópias sem secrets."""
import shutil
import sys
import tempfile
from pathlib import Path
from run_manual_refresh_pipeline_mutations import ROOT, mutations

def main():
    with tempfile.TemporaryDirectory(prefix="mugo-final-mutations-") as temp:
        root=Path(temp); server=root/"server"
        for folder in ["services","routes"]:
            (server/folder).mkdir(parents=True)
            for source in (ROOT/"server"/folder).glob("*.py"): shutil.copyfile(source,server/folder/source.name)
        shutil.copyfile(ROOT/"server/api_support.py",server/"api_support.py")
        (server/"tests").mkdir()
        for source,target in [("test_ads_sync_resilience.py","test_final_ads.py"),("test_provider_refresh.py","test_final_refresh.py")]: shutil.copyfile(ROOT/"server/tests"/source,server/"tests"/target)
        back=[
            ("Ads ignora falha de projeção","services/ads_sync.py",'if projection.get("ok") is False:', 'if False:'),
            ("fachada oculta fonte Ads","services/provider_refresh.py",'label = ", ".join(failed) or "Uma fonte"','label = "Uma fonte"'),
            ("consulta sem dados vira sucesso genérico","services/provider_refresh.py",'result.get("sync_outcome") == "no_data" else "success"','False else "success"'),
        ]
        mutations(server,back,[sys.executable,"-m","unittest","discover","-s","tests","-p","test_final_*.py"])
        for path in (ROOT/"src").rglob("*"):
            if path.is_file() and path.suffix in {".ts",".tsx",".css",".json",".svg"}:
                target=root/path.relative_to(ROOT); target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(path,target)
        for name in ["package.json","vite.config.ts"]: shutil.copyfile(ROOT/name,root/name)
        (root/"node_modules").symlink_to(ROOT/"node_modules",target_is_directory=True)
        front=[
            ("CTA reaparece em Clientes","src/pages/Customers.tsx",'        title="Clientes"','        title="Clientes"\n        controls={<button>Atualizar dados</button>}'),
            ("nome fabricado","src/pages/Customers.tsx",'if (customer.email) return customer.email;', 'if (customer.email) return `Cliente ${customer.external_id}`;'),
            ("Ads sem dados vira sem sync","src/pages/Dashboard.tsx",'paidRefreshNoData === `${period.start}:${period.end}` ?', 'false ?'),
        ]
        mutations(root,front,[str(ROOT/"node_modules/.bin/vitest"),"run","src/pages/Customers.test.tsx","src/pages/Dashboard.channelReport.test.tsx"])
        print("Resultado: 6/6 mutações detectadas")
    return 0
if __name__=="__main__": raise SystemExit(main())
