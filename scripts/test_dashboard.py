"""Local collector regressions. Fixtures are synthetic shapes verified against live CLI output."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
server=load('desk_server',ROOT/'dashboard/server.py')
telemetry=load('desk_telemetry',ROOT/'dashboard/telemetry.py')

def agent(identity='one',provider='codex',status='working',**kwargs):
    value={'id':identity,'provider':provider,'state':status,'role':'general','path':'/project',
           'task':'','updated_at':100,'parent_id':'','pane_key':'','source':'test','confidence':'reported'}
    value.update(kwargs);return value

class DashboardTests(unittest.TestCase):
    def test_collection_schema_is_strict(self):
        self.assertEqual(server.rows({'ok':True,'result':{'worktrees':[]}},'worktrees'),[])
        self.assertEqual(server.rows([],'sessions'),[])
        for invalid in ({'result':{}},{'ok':False,'result':{'sessions':[]}}, {'sessions':[1]}, {'sessions':None}, {'sessions':[],'truncated':True}):
            with self.subTest(invalid=invalid),self.assertRaises(RuntimeError):server.rows(invalid,'sessions')

    def test_live_orca_shape_maps_providers_roots_and_children(self):
        # Same keys/types as worktree ps --json on Orca 2026-11-02; no real names or ids.
        worktrees=[{'repo':'Example','path':'/projects/example','branch':'refs/heads/feat/test','displayName':'feat/test','agents':[
            {'paneKey':'tab:root','parentPaneKey':None,'agentType':'codex','state':'waiting',
             'mainAgent':{'state':'working'},'hasLivePty':True,'updatedAt':1793643220994,
             'conversationName':'Implement example','taskTitle':None,'subagentObservation':'live',
             'subagents':[{'id':'child-thread','state':'waiting','startedAt':1793643206646,'agentType':'reviewer','description':'Review example'}]},
            {'paneKey':'tab:idle','agentType':'claude','state':'done','mainAgent':{'state':'done'},'hasLivePty':True,'updatedAt':1793641425703}
        ]}]
        items,projects=server.map_orca(worktrees,[{'path':'/projects/example','displayName':'Example'},{'path':'/projects/other','displayName':'Other'}])
        self.assertEqual([(x['provider'],x['state']) for x in items],[('codex','working'),('codex','waiting'),('claude','idle')])
        self.assertEqual(items[1]['parent_id'],'tab:root');self.assertEqual(items[1]['role'],'reviewer')
        self.assertEqual(items[1]['task'],'Review example');self.assertEqual(items[0]['task'],'Implement example')
        self.assertEqual(items[0]['updated_at'],1793643220.994)
        self.assertEqual(projects[0]['branch'],'feat/test')
        self.assertTrue(any(x['name']=='Other' for x in projects))
        worktrees[0]['agents'][0]['subagentObservation']='unverifiable'
        self.assertEqual(server.map_orca(worktrees,[])[0][1]['state'],'unknown')

    def test_claude_real_shape_retains_session_id_and_idle(self):
        item=server.clean_agent({'pid':123,'cwd':'/projects/example','kind':'interactive','startedAt':1792605509507,
                                 'sessionId':'claude-session','name':'Example task','status':'idle'},'claude','Claude live')
        self.assertEqual(item['id'],'claude-session');self.assertEqual(item['state'],'idle')
        self.assertEqual(item['task'],'Example task')

    def test_dedup_joins_roots_by_pane_and_children_by_thread_id(self):
        root=agent('tab:root',pane_key='tab:root',source='Orca live')
        child=agent('child-thread',parent_id='tab:root',source='Orca child agent')
        hook=agent('codex:thread',pane_key='tab:root',source='Local lifecycle hook',role='backend',task='Actual assignment')
        hook_child=agent('codex:child-thread',parent_id='codex:thread',pane_key='tab:root',source='Local lifecycle hook')
        history=agent('thread',status='recent',source='Codex recent history')
        result=server.deduplicate([root,child,hook,hook_child,history])
        self.assertEqual(len(result),2);self.assertEqual(result[0]['state'],'working')
        self.assertEqual(result[0]['role'],'backend');self.assertEqual(result[0]['task'],'Actual assignment')
        self.assertEqual(result[1]['parent_id'],'tab:root')

    def test_stale_snapshot_suppresses_every_open_state(self):
        value={'updated_at':100,'agents':[agent(status=x) for x in ('working','waiting','idle','stopped','recent')]}
        result=server.current_snapshot(value,now=130)
        self.assertTrue(result['stale']);self.assertEqual([x['state'] for x in result['agents']],['unknown','unknown','unknown','stopped','recent'])
        self.assertEqual(value['agents'][0]['state'],'working')
        value['stale']=True;value['updated_at']=130
        self.assertTrue(server.current_snapshot(value,now=131)['stale'])

    def test_installed_configuration_absent_does_not_break_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            with patch.object(server,'CODEX',base/'codex'),patch.object(server,'CLAUDE',base/'claude'),patch.object(server,'ROOT',base/'tracker'),patch.object(server,'orca',return_value=([],[])),patch.object(server,'claude',return_value=([],[])),patch.object(server,'telemetry',return_value=([],[])),patch.object(server,'codex_history',return_value=([],[])),patch.object(server,'discover_projects',return_value=[]):
                value=server.snapshot()
                self.assertEqual(value['roles'],[])
                self.assertEqual(value['policy'],{'codex':False,'claude':False})
                self.assertTrue(all(source['ok'] for source in value['sources']))

    def test_roles_and_policy_read_installed_clients_only(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);codex=base/'codex';claude=base/'claude'
            (codex/'agents').mkdir(parents=True);(claude/'agents').mkdir(parents=True)
            (codex/'agents/reviewer.toml').write_text('name = "reviewer"\ndescription = "Review behavior"\n')
            (codex/'agents/broken.toml').write_text('invalid = [')
            (claude/'agents/qa.md').write_text('---\nname: qa\ndescription: "Verify behavior"\n---\nInstructions\n')
            (codex/'AGENTS.md').write_text('Shared personal policy\n')
            (claude/'CLAUDE.md').write_text('Existing personal policy\nShared personal policy\n')
            with patch.object(server,'CODEX',codex),patch.object(server,'CLAUDE',claude),patch.object(server,'ROOT',base/'missing-source-checkout'):
                roles,policy=server.installed_configuration()
                self.assertEqual([role['name'] for role in roles],['qa','reviewer'])
                self.assertEqual(policy,{'codex':True,'claude':True})
                (claude/'CLAUDE.md').write_text('Unrelated policy')
                self.assertFalse(server.installed_configuration()[1]['claude'])

    def test_parent_child_hooks_and_aging(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(telemetry,'STATE',Path(directory)),patch.object(server,'STATE',Path(directory)),patch.dict(telemetry.os.environ,{'ORCA_PANE_KEY':'tab:root'}):
                with self.assertRaises(RuntimeError):server.telemetry()
                telemetry.record('codex',{'session_id':'parent','hook_event_name':'UserPromptSubmit','prompt':'Build example','cwd':'/project'},now=100)
                telemetry.record('codex',{'session_id':'parent','agent_id':'child','agent_type':'reviewer','hook_event_name':'SubagentStart','cwd':'/project'},now=101)
                telemetry.record('codex',{'session_id':'parent','hook_event_name':'SubagentStop'},now=102)
                with patch.object(server.time,'time',return_value=103):
                    values,_=server.telemetry();by_id={x['id']:x for x in values}
                self.assertEqual(by_id['codex:parent']['state'],'working')
                self.assertEqual(by_id['codex:child']['parent_id'],'codex:parent')
                self.assertEqual(by_id['codex:child']['role'],'reviewer')
                telemetry.record('codex',{'session_id':'parent','hook_event_name':'Stop'},now=104)
                telemetry.record('codex',{'session_id':'parent','agent_id':'child','hook_event_name':'SubagentStop'},now=105)
                with patch.object(server.time,'time',return_value=300):
                    values,_=server.telemetry();by_id={x['id']:x for x in values}
                self.assertEqual(by_id['codex:parent']['state'],'unknown')
                self.assertEqual(by_id['codex:child']['state'],'stopped')
                self.assertEqual(by_id['codex:parent']['task'],'Build example')
                self.assertEqual(by_id['codex:parent']['pane_key'],'tab:root')

if __name__=='__main__':unittest.main()
