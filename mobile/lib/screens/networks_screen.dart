import 'package:flutter/material.dart';
import '../api/api_client.dart';
import '../api/models.dart';

class NetworksScreen extends StatefulWidget {
  const NetworksScreen({super.key});
  @override State<NetworksScreen> createState() => _NetworksScreenState();
}

class _NetworksScreenState extends State<NetworksScreen> {
  List<NetworkFile> _files = [];
  bool _loading = true;

  @override void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    try {
      final data = await api.get('/networks');
      setState(() { _files = (data['files'] as List).map((f) => NetworkFile.fromJson(f)).toList(); _loading = false; });
    } catch (e) { setState(() => _loading = false); }
  }

  Future<void> _addCidr(String name) async {
    final ctl = TextEditingController();
    final result = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(
      title: Text('Add CIDR to $name'), content: TextField(controller: ctl, decoration: const InputDecoration(hintText: '192.168.1.0/24'), autofocus: true),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
        ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Add'))],
    ));
    if (result == true && ctl.text.trim().isNotEmpty) {
      try { await api.post('/networks/$name', body: {'cidrs': [ctl.text.trim()]}); _load(); } catch (e) { if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e'))); }
    }
  }

  Future<void> _deleteCidr(String name, String cidr) async {
    try { await api.del('/networks/$name', body: {'cidrs': [cidr]}); _load(); } catch (e) { if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e'))); }
  }

  Future<void> _createFile() async {
    final nameCtl = TextEditingController(), descCtl = TextEditingController(), cidrsCtl = TextEditingController();
    final result = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(
      title: const Text('New Network File'), content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: nameCtl, decoration: const InputDecoration(labelText: 'Name', hintText: 'google')),
        TextField(controller: descCtl, decoration: const InputDecoration(labelText: 'Description')),
        TextField(controller: cidrsCtl, decoration: const InputDecoration(labelText: 'CIDRs (one per line)'), maxLines: 3),
      ]),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
        ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Create'))],
    ));
    if (result == true && nameCtl.text.trim().isNotEmpty) {
      final cidrs = cidrsCtl.text.split('\n').map((s) => s.trim()).where((s) => s.isNotEmpty).toList();
      try { await api.post('/networks', body: {'name': nameCtl.text.trim(), 'description': descCtl.text.trim(), 'cidrs': cidrs}); _load(); } catch (e) { if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e'))); }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    return Scaffold(
      body: RefreshIndicator(onRefresh: _load, child: ListView(children: _files.map((f) => Card(
        margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: ExpansionTile(
          title: Text(f.name, style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle: Text('${f.description} · ${f.entryCount} entries', style: const TextStyle(fontSize: 12, color: Colors.grey)),
          trailing: IconButton(icon: const Icon(Icons.add, size: 20), onPressed: () => _addCidr(f.name)),
          children: f.entries.map((e) => ListTile(
            dense: true, title: Text(e, style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
            trailing: IconButton(icon: const Icon(Icons.close, size: 16, color: Colors.red), onPressed: () => _deleteCidr(f.name, e)),
          )).toList(),
        ),
      )).toList())),
      floatingActionButton: FloatingActionButton(onPressed: _createFile, child: const Icon(Icons.create_new_folder)),
    );
  }
}
