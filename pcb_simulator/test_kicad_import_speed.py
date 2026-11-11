"""Keep native CLI startup constant as board net count grows.

The regression was one costly KiCad process per net. Test the export contract
rather than wall time, so slow CI machines cannot make this check flaky.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pcb_simulator import kicad_preview as kc


class KiCadImportExportCountTests(unittest.TestCase):
    def test_one_native_odb_export_for_one_or_three_hundred_nets(self):
        for count in [1,300]:
            with self.subTest(nets=count),tempfile.TemporaryDirectory() as temporary:
                folder=Path(temporary);source=folder/'source.kicad_pcb';source.write_text('(kicad_pcb)')
                output=folder/'import'
                board=dict(filename=source.name,nets=[dict(name=f'NET_{index}',pads=2,tracks=1,vias=0,zones=0) for index in range(count)],pads=[],bounds_mm=[0,0,10,10])
                renderer_seen=[]
                def render_all(odb,target,passed_board):
                    # The renderer receives the entire inventory in one call.
                    renderer_seen.extend(net['name'] for net in passed_board['nets'])
                    passed_board['preview_source']='native_odb_connectivity'
                    passed_board['colour_layers']={side:dict(net_groups=len(passed_board['nets'])) for side in ['top','bottom']}
                with patch.object(kc,'inventory',return_value=(board,None,None,None)) as inventory, \
                     patch.object(kc,'run_cli') as cli, \
                     patch('pcb_simulator.odb_preview.write_net_plots',side_effect=render_all) as render, \
                     patch.object(kc,'filtered_board',side_effect=AssertionError('Import must not filter/export individual nets.')) as filtered, \
                     patch.object(kc,'plots',side_effect=AssertionError('Import must not start per-net SVG exports.')) as plots, \
                     patch.object(kc.time,'perf_counter',side_effect=[10,10.1,10.6,10.9]):
                    result=kc.inspect_board(source,output,lambda *a,**k:None)
                inventory.assert_called_once_with(source)
                cli.assert_called_once()
                arguments,log_folder=cli.call_args.args
                self.assertEqual(arguments[:3],['pcb','export','odb'])
                self.assertEqual(arguments[arguments.index('--compression')+1],'none')
                self.assertEqual(arguments[arguments.index('--units')+1],'mm')
                self.assertEqual(arguments[arguments.index('--output')+1],output/'odb')
                self.assertEqual(arguments[-1],source)
                self.assertEqual(log_folder,output)
                render.assert_called_once_with(output/'odb',output,board)
                self.assertEqual(renderer_seen,[f'NET_{index}' for index in range(count)])
                filtered.assert_not_called();plots.assert_not_called()
                self.assertEqual(result,dict(board_file='board.json'))
                saved=json.loads((output/'board.json').read_text())
                self.assertEqual(len(saved['nets']),count)
                self.assertEqual(saved['colour_layers']['top']['net_groups'],count)
                self.assertEqual(saved['colour_layers']['bottom']['net_groups'],count)
                self.assertEqual(saved['import_timings'],dict(metadata_seconds=.1,export_seconds=.5,colour_seconds=.3,total_seconds=.9,kicad_exports=1))


if __name__=='__main__':unittest.main()
