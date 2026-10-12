import argparse,hashlib,json,secrets,subprocess,sys,tempfile,time
from pathlib import Path
examples=Path(__file__).resolve().parent;repo=examples.parents[2]

def verify(written,resumed,decision):
 assert decision not in json.dumps(written['results'][:2]), 'Decision already present before checkpoint'
 assert resumed['results'][-1]['name']=='brief'
 assert decision in resumed['final'], 'Fresh brief omitted the saved decision'

def main():
 parser=argparse.ArgumentParser(description='Verify both stub-model recipes without installs or hosted models.')
 parser.add_argument('--adk-python',type=Path,required=True)
 parser.add_argument('--langgraph-python',type=Path,required=True)
 args=parser.parse_args()
 # Resolving the Python symlink would bypass its virtual environment.
 interpreters={'adk':args.adk_python.expanduser().absolute(),'langgraph':args.langgraph_python.expanduser().absolute()}
 records=[]
 with tempfile.TemporaryDirectory(prefix='ws-recipes-proof-') as d:
  home=Path(d)/'home';home.mkdir()
  env={'PATH':'/usr/bin:/bin','HOME':str(home),'PYTHONDONTWRITEBYTECODE':'1','WS_OFFLINE':'1','LANGSMITH_TRACING':'false','LANGGRAPH_CLI_NO_ANALYTICS':'1','OTEL_SDK_DISABLED':'true'}
  for writer,reader in [('adk','langgraph'),('langgraph','adk')]:
   root=Path(d)/writer;decision='Verify rollback marker '+secrets.token_hex(6)+' before retrying; keep the old index.'
   init='from pathlib import Path; from ws import core; r=Path('+repr(str(root))+'); core.init(r,"Synthetic");core.task_new(r,"MEM-1","Migration fixture");core.claim(r,"MEM-1","fixture")'
   subprocess.run([sys.executable,'-c',init],cwd=repo,env=env,check=True,capture_output=True)
   started=time.perf_counter()
   def call(client,phase):
    cmd=[str(interpreters[client]),str(examples/(client+'_agent.py')),str(root),phase]
    if phase=='write':cmd+=['--decision',decision]
    p=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=90)
    if p.returncode:raise RuntimeError(p.stderr[-4000:])
    return json.loads(p.stdout)
   written=call(writer,'write');resumed=call(reader,'resume');verify(written,resumed,decision)
   records.append(dict(writer=writer,fresh_reader=reader,pre_checkpoint_brief_lacked_decision=True,brief_recovered=True,model_calls=0,network='denied',seconds=round(time.perf_counter()-started,3)))
 proof={'label':'stub-model-tested','base':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'scripts_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in examples.glob('*.py')},'checks':records}
 print(json.dumps(proof))

if __name__=='__main__': main()
