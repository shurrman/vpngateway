import 'package:flutter/material.dart';
import 'api/api_client.dart';
import 'screens/dashboard_screen.dart';
import 'screens/domains_screen.dart';
import 'screens/networks_screen.dart';
import 'screens/routing_screen.dart';
import 'screens/services_screen.dart';
import 'screens/dns_screen.dart';
import 'screens/settings_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await api.initSsl();
  runApp(const VpnGatewayApp());
}

class VpnGatewayApp extends StatelessWidget {
  const VpnGatewayApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'VPN Gateway',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: const Color(0xFF6C8CFF),
        brightness: Brightness.dark,
        useMaterial3: true,
      ),
      home: const MainShell(),
    );
  }
}

class MainShell extends StatefulWidget {
  const MainShell({super.key});
  @override State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _index = 0;

  static const _titles = ['Dashboard', 'Domains', 'Networks', 'Routing', 'More'];

  final _screens = <Widget>[
    const DashboardScreen(),
    const DomainsScreen(),
    const NetworksScreen(),
    const RoutingScreen(),
    const _MoreScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_titles[_index])),
      body: IndexedStack(index: _index, children: _screens),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.dashboard), label: 'Dashboard'),
          NavigationDestination(icon: Icon(Icons.language), label: 'Domains'),
          NavigationDestination(icon: Icon(Icons.hub), label: 'Networks'),
          NavigationDestination(icon: Icon(Icons.route), label: 'Routing'),
          NavigationDestination(icon: Icon(Icons.more_horiz), label: 'More'),
        ],
      ),
    );
  }
}

class _MoreScreen extends StatelessWidget {
  const _MoreScreen();

  @override
  Widget build(BuildContext context) {
    return ListView(children: [
      ListTile(leading: const Icon(Icons.miscellaneous_services), title: const Text('Services'),
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => Scaffold(appBar: AppBar(title: const Text('Services')), body: const ServicesScreen())))),
      ListTile(leading: const Icon(Icons.dns), title: const Text('DNS'),
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => Scaffold(appBar: AppBar(title: const Text('DNS')), body: const DnsScreen())))),
      ListTile(leading: const Icon(Icons.settings), title: const Text('Settings'),
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => Scaffold(appBar: AppBar(title: const Text('Settings')), body: const SettingsScreen())))),
    ]);
  }
}
