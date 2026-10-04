"""Health gates under controlled files and transport; no real inference/EDA."""
import hashlib,io,json,os
from pathlib import Path
import subprocess,tempfile,threading,unittest,urllib.error,urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from test_bridge import app
hp=app.health_probe

def fixture(root,ipv6=False,address=None,port=8000):
    proc=root/'proc';drm=root/'drm';(proc/'net').mkdir(parents=True)
    value=address or ('00000000000000000000000001000000' if ipv6 else '0100007F')
    line=f'0: {value}:{port:04X} 00000000:0000 0A 0:0 00:0 0 0 0 991\n'
    for name in ['tcp','tcp6']:(proc/'net'/name).write_text('header\n'+(line if name==('tcp6' if ipv6 else 'tcp') else ''))
    pid=proc/'123';(pid/'fd').mkdir(parents=True)
    # identity() uses Linux fields after ')' including the process state.
    (pid/'stat').write_text('123 (llama-server) '+' '.join(['S']+['0']*18+['555']))
    links={pid/'fd/4':'socket:[991]',pid/'fd/5':'/dev/dri/renderD133',pid/'fd/6':'/dev/dri/renderD133'}
    for node,used in [('renderD133',19*1024**3),('renderD134',29*1024**3)]:
        dev=drm/node/'device';dev.mkdir(parents=True)
        (dev/'vendor').write_text('0x1002');(dev/'mem_info_vram_used').write_text(str(used));(dev/'mem_info_vram_total').write_text(str(48*1024**3))
    def readlink(p):return links[Path(p)]
    for p in links:p.touch()
    return proc,drm,pid,links,readlink

class Health(unittest.TestCase):
    def setUp(self):hp.VERSIONS.clear()
    def test_version_lowercase_uppercase_and_transient_failure_recovers(self):
        class Process:
            pid=0
            def __init__(self,*a,**k):self.returncode=0
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def poll(self):return self.returncode
            def communicate(self,**kwargs):return self.text,None
        for text in ['vivado v2026.1 (64-bit)','Vivado v2026.1 (64-bit)']:
            hp.VERSIONS.clear();Process.text=text
            with patch.object(hp.subprocess,'Popen',Process),patch.object(hp,'_stop_owned'):
                self.assertEqual(hp.vivado_version('/fake/vivado'),'2026.1')
        hp.VERSIONS.clear()
        with patch.object(hp.subprocess,'Popen',side_effect=OSError('temporarily missing')):self.assertIsNone(hp.vivado_version('/fake/vivado'))
        Process.text='vivado v2026.1'
        with patch.object(hp.subprocess,'Popen',Process),patch.object(hp,'_stop_owned'):self.assertEqual(hp.vivado_version('/fake/vivado'),'2026.1')
    def test_unique_endpoint_one_card_deduplicates_descriptors_and_excludes_others(self):
        with tempfile.TemporaryDirectory() as td:
            proc,drm,pid,links,readlink=fixture(Path(td))
            with patch.object(hp.os,'readlink',side_effect=readlink):obs=hp.observe('http://127.0.0.1:8000/v1',proc,drm)
            self.assertEqual(obs['vram_gb'],19);self.assertEqual(obs['model_pid'],123);self.assertEqual(obs['render_node'],'renderD133')
    def test_ambiguous_multiple_gpu_missing_nonamd_and_dead_owner_are_unknown(self):
        for kind in ['second_owner','two_gpu','no_gpu','nonamd','dead','counter_missing','counter_invalid']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td:
                proc,drm,pid,links,readlink=fixture(Path(td));used=drm/'renderD133/device/mem_info_vram_used'
                if kind=='second_owner':
                    other=proc/'124';(other/'fd').mkdir(parents=True);(other/'fd/1').touch();links[other/'fd/1']='socket:[991]'
                elif kind=='two_gpu':(pid/'fd/7').touch();links[pid/'fd/7']='/dev/dri/renderD134'
                elif kind=='no_gpu':links[pid/'fd/5']=links[pid/'fd/6']='/dev/null'
                elif kind=='nonamd':(drm/'renderD133/device/vendor').write_text('0x10de')
                elif kind=='dead':(pid/'stat').write_text((pid/'stat').read_text().replace(') S',') Z'))
                elif kind=='counter_missing':used.unlink()
                else:used.write_text('-1')
                with patch.object(hp.os,'readlink',side_effect=readlink):self.assertIsNone(hp.observe('http://127.0.0.1:8000/v1',proc,drm))
    def test_ipv6_and_address_binding_no_remote_or_wrong_address_attribution(self):
        for ipv6,addr,endpoint,valid in [(True,None,'http://[::1]:8000/v1',True),(False,'00000000','http://localhost:8000/v1',True),(False,'0200007F','http://127.0.0.1:8000/v1',False),(False,None,'http://example.invalid:8000/v1',False),(False,None,'http://127.0.0.1:9000/v1',False)]:
            with self.subTest(endpoint=endpoint),tempfile.TemporaryDirectory() as td:
                proc,drm,pid,links,readlink=fixture(Path(td),ipv6,addr)
                with patch.object(hp.os,'readlink',side_effect=readlink):self.assertEqual(hp.observe(endpoint,proc,drm) is not None,valid)
    def test_raw_32gib_boundary_unknown_and_package_integrity_gates(self):
        with patch.dict(os.environ,RTL_PROFILE='submission',MODEL_NAME='fake-model'),patch.object(app.core,'models',return_value=['fake-model']),patch.object(app.core,'vivado_tool',return_value='/fake/vivado'),patch.object(app.core,'vivado_version',return_value='2026.1'):
            for used,ready in [(32,True),(32+1/1024**3,False),(None,False)]:
                with patch.object(app.core,'vram_gb',return_value=used):self.assertEqual(app.health()['ready'],ready)
            with patch.object(app,'verify_package',side_effect=ValueError('staged byte changed')):self.assertFalse(app.health()['ready'])
    def test_authenticated_http_health_exact_fields_and_recovery(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),app.core.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def get(token):
            req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/v1/health',headers={'Authorization':'Bearer '+token})
            with urllib.request.urlopen(req,timeout=5) as r:return json.load(r)
        try:
            with patch.dict(os.environ,FPGACHINA_TOKEN='local-test-only',RTL_PROFILE='submission',MODEL_NAME='fake-model'),patch.object(app.core,'models',return_value=['fake-model']),patch.object(app.core,'vivado_tool',return_value='/fake/vivado'),patch.object(app.core,'vivado_version',return_value='2026.1'),patch.object(app.core,'vram_gb',return_value=19):
                with self.assertRaises(urllib.error.HTTPError) as caught:get('wrong')
                self.assertEqual(caught.exception.code,401)
                self.assertEqual(get('local-test-only'),{'ready':True,'track':'rtl','model':'fake-model','vram_gb':19})
                with patch.object(app.core,'models',side_effect=OSError('unavailable')):self.assertFalse(get('local-test-only')['ready'])
                self.assertTrue(get('local-test-only')['ready'])
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
