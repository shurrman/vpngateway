import 'package:flutter/material.dart';
import '../api/api_client.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _urlCtl = TextEditingController();
  bool _connected = false;
  bool _testing = false;
  String? _apiVersion;

  @override
  void initState() {
    super.initState();
    _urlCtl.text = api.baseUrl;
    _loadApiVersion();
  }

  Future<void> _loadApiVersion() async {
    try {
      final ok = await api.testConnection();
      if (ok) {
        setState(() => _apiVersion = api.apiVersion);
      }
    } catch (_) {}
  }

  Future<void> _testConnection() async {
    setState(() => _testing = true);
    await api.setBaseUrl(_urlCtl.text.trim());
    final ok = await api.testConnection();
    setState(() {
      _connected = ok;
      _testing = false;
    });
    final msg = ok
        ? 'Connected successfully'
        : 'Connection failed: ${api.lastError ?? "unknown error"}';
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(msg),
          backgroundColor: ok ? Colors.green : Colors.red,
          duration: const Duration(seconds: 8),
        ),
      );
    }
  }

  Future<void> _testEmail() async {
    try {
      final resp = await api.post('/notifications/test');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(resp['log']?.toString() ?? 'Sent')),
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
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'API Connection',
                  style: TextStyle(color: Colors.grey, fontSize: 12),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: _urlCtl,
                  decoration: const InputDecoration(
                    labelText: 'API Base URL',
                    hintText: 'http://192.168.50.2:8080',
                  ),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    ElevatedButton(
                      onPressed: _testing ? null : _testConnection,
                      child: _testing
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Test Connection'),
                    ),
                    if (_connected)
                      const Padding(
                        padding: EdgeInsets.only(left: 8),
                        child: Icon(Icons.check_circle, color: Colors.green),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Email Notifications',
                  style: TextStyle(color: Colors.grey, fontSize: 12),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Configure SMTP settings in the web console at /notifications',
                  style: TextStyle(fontSize: 13, color: Colors.grey),
                ),
                const SizedBox(height: 12),
                ElevatedButton.icon(
                  onPressed: _testEmail,
                  icon: const Icon(Icons.email),
                  label: const Text('Send Test Email'),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'About',
                  style: TextStyle(color: Colors.grey, fontSize: 12),
                ),
                const SizedBox(height: 8),
                const Text(
                  'VPN Gateway Admin',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 4),
                const Text(
                  'App: v1.3.0',
                  style: TextStyle(fontSize: 13, color: Colors.grey),
                ),
                Text(
                  'API: ${_apiVersion ?? "..."}',
                  style: const TextStyle(fontSize: 13, color: Colors.grey),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
