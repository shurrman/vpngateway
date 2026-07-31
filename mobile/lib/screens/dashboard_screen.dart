import 'dart:async';
import 'package:flutter/material.dart';
import '../api/api_client.dart';
import '../api/models.dart';
import 'settings_screen.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  DashboardStatus? _status;
  String _mode = 'split';
  Timer? _timer;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 10), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final data = await api.get('/system/status');
      final modeData = await api.get('/routing/mode');
      if (mounted) {
        setState(() {
          _status = DashboardStatus.fromJson(data);
          _mode = modeData['mode'] ?? 'split';
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_status == null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, size: 48, color: Colors.red),
            const SizedBox(height: 8),
            const Text('Failed to connect'),
            Text(
              api.baseUrl,
              style: const TextStyle(fontSize: 12, color: Colors.grey),
            ),
            const SizedBox(height: 16),
            ElevatedButton(onPressed: _load, child: const Text('Retry')),
            const SizedBox(height: 8),
            TextButton(
              onPressed: () async {
                await Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => Scaffold(
                      appBar: AppBar(title: const Text('Settings')),
                      body: const SettingsScreen(),
                    ),
                  ),
                );
                _load();
              },
              child: const Text('Open Settings'),
            ),
          ],
        ),
      );
    }

    final s = _status!;
    final modeLabels = {
      'split': 'Split Tunneling',
      'all-vpn': 'All VPN',
      'all-direct': 'All Direct',
    };
    final modeColors = {
      'split': Colors.blue,
      'all-vpn': Colors.green,
      'all-direct': Colors.orange,
    };

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Mode badge
          Center(
            child: Chip(
              label: Text(
                modeLabels[_mode] ?? _mode,
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
              ),
              backgroundColor: modeColors[_mode] ?? Colors.blue,
            ),
          ),
          const SizedBox(height: 16),
          // VPN & LAN
          Row(
            children: [
              Expanded(child: _ifaceCard('VPN', s.vpn)),
              const SizedBox(width: 12),
              Expanded(child: _ifaceCard('LAN', s.lan)),
            ],
          ),
          const SizedBox(height: 12),
          // Internet connectivity
          _connectivityCard(s),
          const SizedBox(height: 12),
          // Counters
          Row(
            children: [
              Expanded(
                child: _statCard(
                  'Domains',
                  s.domainsCount.toString(),
                  Icons.language,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _statCard(
                  'IPSet',
                  s.ipsetEntries.toString(),
                  Icons.filter_list,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          // Services
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Services',
                    style: Theme.of(
                      context,
                    ).textTheme.labelLarge?.copyWith(color: Colors.grey),
                  ),
                  const SizedBox(height: 8),
                  ...s.services.entries.map(
                    (e) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: Row(
                        children: [
                          Icon(
                            Icons.circle,
                            size: 10,
                            color: e.value ? Colors.green : Colors.red,
                          ),
                          const SizedBox(width: 8),
                          Text(e.key, style: const TextStyle(fontSize: 13)),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          // Resources
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Resources',
                    style: Theme.of(
                      context,
                    ).textTheme.labelLarge?.copyWith(color: Colors.grey),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    s.resources.uptime,
                    style: const TextStyle(fontSize: 13),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Memory: ${s.resources.memUsedMb} / ${s.resources.memTotalMb} MB',
                    style: const TextStyle(fontSize: 13),
                  ),
                  const SizedBox(height: 4),
                  LinearProgressIndicator(
                    value: s.resources.memPercent / 100,
                    color: s.resources.memPercent > 80
                        ? Colors.red
                        : Colors.blue,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Load: ${s.resources.loadAverage.join(', ')} · CPU: ${s.resources.cpuCount}',
                    style: const TextStyle(fontSize: 13, color: Colors.grey),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _ifaceCard(String label, InterfaceInfo iface) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(
              context,
            ).textTheme.labelLarge?.copyWith(color: Colors.grey),
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              Icon(
                Icons.circle,
                size: 10,
                color: iface.up ? Colors.green : Colors.red,
              ),
              const SizedBox(width: 6),
              Text(
                iface.up ? 'Up' : 'Down',
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
          if (iface.ipAddress != null)
            Text(
              iface.ipAddress!,
              style: const TextStyle(fontSize: 12, color: Colors.grey),
            ),
          Text(
            'TX: ${formatBytes(iface.txBytes)}',
            style: const TextStyle(fontSize: 11, color: Colors.grey),
          ),
          Text(
            'RX: ${formatBytes(iface.rxBytes)}',
            style: const TextStyle(fontSize: 11, color: Colors.grey),
          ),
        ],
      ),
    ),
  );

  Widget _connectivityCard(DashboardStatus s) {
    final gw = s.connectivity?['gateway'];
    final inet = s.connectivity?['internet'];
    final gwOk = gw?['reachable'] == true;
    final inetOk = inet?['reachable'] == true;
    final gwIp = gw?['ip'] ?? '?';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Internet',
              style: Theme.of(
                context,
              ).textTheme.labelLarge?.copyWith(color: Colors.grey),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Icon(
                  Icons.circle,
                  size: 10,
                  color: gwOk ? Colors.green : Colors.red,
                ),
                const SizedBox(width: 8),
                Text('Gateway $gwIp', style: const TextStyle(fontSize: 13)),
              ],
            ),
            const SizedBox(height: 4),
            Row(
              children: [
                Icon(
                  Icons.circle,
                  size: 10,
                  color: inetOk ? Colors.green : Colors.red,
                ),
                const SizedBox(width: 8),
                const Text(
                  'Internet (8.8.8.8)',
                  style: TextStyle(fontSize: 13),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _statCard(String label, String value, IconData icon) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          Icon(icon, color: Colors.blue, size: 28),
          const SizedBox(height: 8),
          Text(
            value,
            style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
          ),
          Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey)),
        ],
      ),
    ),
  );
}
