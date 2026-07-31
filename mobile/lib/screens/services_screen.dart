import 'package:flutter/material.dart';
import '../api/api_client.dart';
import '../api/models.dart';

class ServicesScreen extends StatefulWidget {
  const ServicesScreen({super.key});
  @override
  State<ServicesScreen> createState() => _ServicesScreenState();
}

class _ServicesScreenState extends State<ServicesScreen> {
  List<ServiceInfo> _services = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await api.get('/services');
      setState(() {
        _services = (data['services'] as List)
            .map((s) => ServiceInfo.fromJson(s))
            .toList();
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _loading = false;
        _error = '$e';
      });
    }
  }

  Future<void> _action(String name, String action) async {
    if (action == 'stop') {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text('Stop $name?'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel'),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Stop'),
            ),
          ],
        ),
      );
      if (ok != true) return;
    }
    try {
      final resp = await api.post('/services/$name/$action');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(resp['log']?.toString() ?? 'Done')),
        );
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

  Future<void> _showLogs(String name) async {
    try {
      final data = await api.get('/services/$name/logs?lines=100');
      if (!mounted) return;
      showModalBottomSheet(
        context: context,
        isScrollControlled: true,
        builder: (ctx) => DraggableScrollableSheet(
          initialChildSize: 0.7,
          minChildSize: 0.3,
          maxChildSize: 0.95,
          expand: false,
          builder: (ctx, ctl) => Column(
            children: [
              Padding(
                padding: const EdgeInsets.all(12),
                child: Text(
                  '$name logs',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 16,
                  ),
                ),
              ),
              Expanded(
                child: SingleChildScrollView(
                  controller: ctl,
                  padding: const EdgeInsets.all(12),
                  child: Text(
                    data['logs'] ?? '',
                    style: const TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 11,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      );
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
    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, size: 48, color: Colors.red),
            const SizedBox(height: 8),
            Text(
              _error!,
              style: const TextStyle(fontSize: 12, color: Colors.grey),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            ElevatedButton(onPressed: _load, child: const Text('Retry')),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        children: _services
            .map(
              (s) => Card(
                margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                child: ListTile(
                  leading: Icon(
                    Icons.circle,
                    size: 14,
                    color: s.active ? Colors.green : Colors.red,
                  ),
                  title: Text(
                    s.name,
                    style: const TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 14,
                    ),
                  ),
                  subtitle: Text(s.state, style: const TextStyle(fontSize: 12)),
                  trailing: PopupMenuButton<String>(
                    onSelected: (v) {
                      if (v == 'logs') {
                        _showLogs(s.name);
                      } else {
                        _action(s.name, v);
                      }
                    },
                    itemBuilder: (_) => [
                      if (!s.active)
                        const PopupMenuItem(
                          value: 'start',
                          child: Text('Start'),
                        ),
                      if (s.active)
                        const PopupMenuItem(
                          value: 'restart',
                          child: Text('Restart'),
                        ),
                      if (s.active)
                        const PopupMenuItem(value: 'stop', child: Text('Stop')),
                      const PopupMenuItem(value: 'logs', child: Text('Logs')),
                    ],
                  ),
                ),
              ),
            )
            .toList(),
      ),
    );
  }
}
