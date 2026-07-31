import 'package:flutter/material.dart';
import '../api/api_client.dart';
import '../api/models.dart';

class DomainsScreen extends StatefulWidget {
  const DomainsScreen({super.key});
  @override
  State<DomainsScreen> createState() => _DomainsScreenState();
}

class _DomainsScreenState extends State<DomainsScreen> {
  List<DomainGroup> _groups = [];
  int _total = 0;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final data = await api.get('/domains');
      setState(() {
        _groups = (data['groups'] as List)
            .map((g) => DomainGroup.fromJson(g))
            .toList();
        _total = data['total'] ?? 0;
        _loading = false;
      });
    } catch (e) {
      setState(() => _loading = false);
    }
  }

  Future<void> _addDomain() async {
    final domainCtl = TextEditingController();
    final groupCtl = TextEditingController();
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Add Domain'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: domainCtl,
              decoration: const InputDecoration(
                labelText: 'Domain',
                hintText: 'example.com',
              ),
              autofocus: true,
            ),
            const SizedBox(height: 8),
            TextField(
              controller: groupCtl,
              decoration: const InputDecoration(labelText: 'Group (optional)'),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Add'),
          ),
        ],
      ),
    );
    if (result == true && domainCtl.text.trim().isNotEmpty) {
      try {
        final resp = await api.post(
          '/domains',
          body: {
            'domains': [domainCtl.text.trim()],
            'group': groupCtl.text.trim().isEmpty ? null : groupCtl.text.trim(),
          },
        );
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text(resp['log'] ?? 'Added')));
        }
        _load();
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text('$e')));
        }
      }
    }
  }

  Future<void> _deleteDomain(String domain) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete domain?'),
        content: Text(domain),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok == true) {
      try {
        await api.del(
          '/domains',
          body: {
            'domains': [domain],
          },
        );
        _load();
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text('$e')));
        }
      }
    }
  }

  Future<void> _checkDomain(String domain) async {
    try {
      final resp = await api.post('/domains/check', body: {'domain': domain});
      final data = resp['data'];
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              '${data['resolved_ips']?.join(', ') ?? 'no IP'} — ${data['in_vpn_ipset'] == true ? 'IN VPN' : 'NOT in VPN'}',
            ),
            duration: const Duration(seconds: 4),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    return Scaffold(
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                '$_total domains',
                style: const TextStyle(color: Colors.grey),
              ),
            ),
            ..._groups.map(
              (g) => ExpansionTile(
                title: Text(
                  '${g.name} (${g.domains.length})',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                children: g.domains
                    .map(
                      (d) => ListTile(
                        title: Text(
                          d,
                          style: const TextStyle(
                            fontFamily: 'monospace',
                            fontSize: 14,
                          ),
                        ),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            IconButton(
                              icon: const Icon(
                                Icons.check_circle_outline,
                                size: 20,
                              ),
                              onPressed: () => _checkDomain(d),
                            ),
                            IconButton(
                              icon: const Icon(
                                Icons.delete_outline,
                                size: 20,
                                color: Colors.red,
                              ),
                              onPressed: () => _deleteDomain(d),
                            ),
                          ],
                        ),
                      ),
                    )
                    .toList(),
              ),
            ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _addDomain,
        child: const Icon(Icons.add),
      ),
    );
  }
}
