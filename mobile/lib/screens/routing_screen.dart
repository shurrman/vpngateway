import 'package:flutter/material.dart';
import '../api/api_client.dart';
import '../api/models.dart';

class RoutingScreen extends StatefulWidget {
  const RoutingScreen({super.key});
  @override State<RoutingScreen> createState() => _RoutingScreenState();
}

class _RoutingScreenState extends State<RoutingScreen> with SingleTickerProviderStateMixin {
  String _mode = 'split';
  late TabController _tabCtl;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _tabCtl = TabController(length: 3, vsync: this);
    _loadMode();
  }
  @override void dispose() { _tabCtl.dispose(); super.dispose(); }

  Future<void> _loadMode() async {
    try { final data = await api.get('/routing/mode'); setState(() { _mode = data['mode'] ?? 'split'; _loading = false; }); }
    catch (e) { setState(() => _loading = false); }
  }

  Future<void> _setMode(String mode) async {
    final labels = {'split': 'Split Tunneling', 'all-vpn': 'All VPN', 'all-direct': 'All Direct'};
    final ok = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(
      title: const Text('Switch mode?'), content: Text('Change to ${labels[mode]}?'),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
        ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Switch'))],
    ));
    if (ok == true) {
      try {
        final resp = await api.post('/routing/mode', body: {'mode': mode});
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(resp['log']?.toString().substring(0, 100) ?? 'Done')));
        _loadMode();
      } catch (e) { if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e'))); }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    return Column(children: [
      // Mode selector
      Padding(padding: const EdgeInsets.all(12), child: SegmentedButton<String>(
        segments: const [
          ButtonSegment(value: 'split', label: Text('Split'), icon: Icon(Icons.call_split)),
          ButtonSegment(value: 'all-vpn', label: Text('All VPN'), icon: Icon(Icons.vpn_lock)),
          ButtonSegment(value: 'all-direct', label: Text('Direct'), icon: Icon(Icons.public)),
        ],
        selected: {_mode},
        onSelectionChanged: (s) => _setMode(s.first),
      )),
      TabBar(controller: _tabCtl, tabs: const [Tab(text: 'IP Rules'), Tab(text: 'Routes'), Tab(text: 'IPSet')]),
      Expanded(child: TabBarView(controller: _tabCtl, children: [_RulesTab(), _RoutesTab(), _IpsetTab()])),
    ]);
  }
}

class _RulesTab extends StatefulWidget { @override State<_RulesTab> createState() => _RulesTabState(); }
class _RulesTabState extends State<_RulesTab> {
  List<Map<String, dynamic>> _rules = [];
  @override void initState() { super.initState(); _load(); }
  Future<void> _load() async {
    try { final data = await api.get('/routing/rules'); setState(() => _rules = List<Map<String, dynamic>>.from(data['rules'] ?? [])); } catch (_) {}
  }
  @override Widget build(BuildContext context) => RefreshIndicator(onRefresh: _load, child: ListView(children: _rules.map((r) => ListTile(
    dense: true, leading: Text('${r['priority']}', style: const TextStyle(fontFamily: 'monospace')),
    title: Text(r['selector'] ?? '', style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
    subtitle: Text(r['action'] ?? ''),
  )).toList()));
}

class _RoutesTab extends StatefulWidget { @override State<_RoutesTab> createState() => _RoutesTabState(); }
class _RoutesTabState extends State<_RoutesTab> {
  List<RouteInfo> _main = [], _t100 = [];
  @override void initState() { super.initState(); _load(); }
  Future<void> _load() async {
    try {
      final data = await api.get('/routing/tables');
      setState(() {
        _main = (data['main'] as List).map((r) => RouteInfo.fromJson(r)).toList();
        _t100 = (data['table_100'] as List).map((r) => RouteInfo.fromJson(r)).toList();
      });
    } catch (_) {}
  }
  Widget _routeList(String title, List<RouteInfo> routes) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Padding(padding: const EdgeInsets.fromLTRB(16, 16, 16, 8), child: Text(title, style: TextStyle(color: Colors.blue[300], fontWeight: FontWeight.bold))),
    ...routes.map((r) => ListTile(dense: true, title: Text(r.destination, style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
      subtitle: Text('via ${r.gateway ?? '—'} dev ${r.device}', style: const TextStyle(fontSize: 12)))),
  ]);
  @override Widget build(BuildContext context) => RefreshIndicator(onRefresh: _load, child: ListView(children: [_routeList('Main Table', _main), _routeList('Table 100 (VPN)', _t100)]));
}

class _IpsetTab extends StatefulWidget { @override State<_IpsetTab> createState() => _IpsetTabState(); }
class _IpsetTabState extends State<_IpsetTab> {
  IpsetInfo? _info;
  final _ipCtl = TextEditingController();
  String? _testResult;
  @override void initState() { super.initState(); _load(); }
  Future<void> _load() async {
    try { final data = await api.get('/routing/ipset'); setState(() => _info = IpsetInfo.fromJson(data)); } catch (_) {}
  }
  Future<void> _testIp() async {
    if (_ipCtl.text.trim().isEmpty) return;
    try {
      final data = await api.get('/routing/ipset/test/${_ipCtl.text.trim()}');
      setState(() => _testResult = data['in_set'] == true ? 'IN VPN set' : 'NOT in set');
    } catch (e) { setState(() => _testResult = 'Error: $e'); }
  }
  @override Widget build(BuildContext context) {
    if (_info == null) return const Center(child: CircularProgressIndicator());
    return RefreshIndicator(onRefresh: _load, child: ListView(padding: const EdgeInsets.all(16), children: [
      Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('vpn_domains', style: TextStyle(color: Colors.grey, fontSize: 12)),
        Text('${_info!.entries}', style: const TextStyle(fontSize: 32, fontWeight: FontWeight.bold)),
        Text('of ${_info!.maxEntries} max · ${formatBytes(_info!.memoryBytes)}', style: const TextStyle(fontSize: 12, color: Colors.grey)),
      ]))),
      const SizedBox(height: 16),
      Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(children: [
        Row(children: [
          Expanded(child: TextField(controller: _ipCtl, decoration: const InputDecoration(hintText: '8.8.8.8', isDense: true), onSubmitted: (_) => _testIp())),
          const SizedBox(width: 8),
          ElevatedButton(onPressed: _testIp, child: const Text('Test')),
        ]),
        if (_testResult != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_testResult!, style: TextStyle(
          color: _testResult!.contains('IN VPN') ? Colors.green : Colors.red, fontWeight: FontWeight.bold))),
      ]))),
    ]));
  }
}
