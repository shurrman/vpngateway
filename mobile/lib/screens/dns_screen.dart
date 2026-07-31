import 'package:flutter/material.dart';
import '../api/api_client.dart';

class DnsScreen extends StatefulWidget {
  const DnsScreen({super.key});
  @override State<DnsScreen> createState() => _DnsScreenState();
}

class _DnsScreenState extends State<DnsScreen> {
  Map<String, dynamic>? _config;
  final _domainCtl = TextEditingController();
  String _queryType = 'A';
  List<String> _results = [];
  bool _loading = true;
  bool _querying = false;
  String? _error;

  @override void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    try { final data = await api.get('/dns/config'); setState(() { _config = data; _loading = false; }); }
    catch (e) { setState(() => _loading = false); }
  }

  Future<void> _query() async {
    if (_domainCtl.text.trim().isEmpty) return;
    setState(() { _querying = true; _error = null; _results = []; });
    try {
      final resp = await api.post('/dns/query', body: {'domain': _domainCtl.text.trim(), 'type': _queryType});
      final data = resp['data'] as Map<String, dynamic>?;
      final records = List<String>.from(data?['records'] ?? []);
      setState(() { _results = records.isEmpty ? ['No records found'] : records; _querying = false; });
    } catch (e) {
      setState(() { _error = '$e'; _querying = false; });
    }
  }

  Future<void> _flush() async {
    try { await api.post('/dns/flush'); if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('DNS cache flushed'))); }
    catch (e) { if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e'))); }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    return RefreshIndicator(onRefresh: _load, child: ListView(padding: const EdgeInsets.all(16), children: [
      if (_config != null) ...[
        Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Upstream DNS', style: TextStyle(color: Colors.grey, fontSize: 12)),
          ...(_config!['upstream_servers'] as List? ?? []).map((s) => Text('$s', style: const TextStyle(fontFamily: 'monospace', fontSize: 14))),
          const SizedBox(height: 12),
          const Text('Local Zones', style: TextStyle(color: Colors.grey, fontSize: 12)),
          ...(_config!['local_zones'] as List? ?? []).map((z) => Text('.${z['zone']} → ${z['server']}', style: const TextStyle(fontSize: 14))),
          const SizedBox(height: 12),
          Text('Cache: ${_config!['cache_size']}', style: const TextStyle(fontSize: 13, color: Colors.grey)),
        ]))),
      ],
      const SizedBox(height: 16),
      Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('DNS Query', style: TextStyle(color: Colors.grey, fontSize: 12)),
        const SizedBox(height: 8),
        TextField(controller: _domainCtl, decoration: const InputDecoration(hintText: 'youtube.com', isDense: true), onSubmitted: (_) => _query()),
        const SizedBox(height: 8),
        Row(children: [
          DropdownButton<String>(value: _queryType, items: ['A','AAAA','CNAME','MX','TXT'].map((t) => DropdownMenuItem(value: t, child: Text(t))).toList(), onChanged: (v) => setState(() => _queryType = v!)),
          const SizedBox(width: 12),
          Expanded(child: ElevatedButton.icon(onPressed: _querying ? null : _query, icon: _querying ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.search), label: const Text('Query'))),
        ]),
        if (_results.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 12), child: Container(
          width: double.infinity,
          padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: Colors.black26, borderRadius: BorderRadius.circular(8)),
          child: Text(_results.join('\n'), style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
        )),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: const TextStyle(color: Colors.red, fontSize: 12))),
      ]))),
      const SizedBox(height: 16),
      ElevatedButton.icon(onPressed: _flush, icon: const Icon(Icons.refresh), label: const Text('Flush DNS Cache')),
    ]));
  }
}
