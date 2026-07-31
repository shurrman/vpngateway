class InterfaceInfo {
  final String name;
  final bool up;
  final String? ipAddress;
  final int txBytes;
  final int rxBytes;

  InterfaceInfo({required this.name, required this.up, this.ipAddress, this.txBytes = 0, this.rxBytes = 0});

  factory InterfaceInfo.fromJson(Map<String, dynamic> j) => InterfaceInfo(
    name: j['name'] ?? '', up: j['up'] ?? false, ipAddress: j['ip_address'],
    txBytes: j['tx_bytes'] ?? 0, rxBytes: j['rx_bytes'] ?? 0,
  );
}

class SystemResources {
  final String uptime;
  final List<double> loadAverage;
  final int memTotalMb, memUsedMb;
  final double memPercent;
  final int cpuCount;

  SystemResources({required this.uptime, required this.loadAverage, required this.memTotalMb,
    required this.memUsedMb, required this.memPercent, required this.cpuCount});

  factory SystemResources.fromJson(Map<String, dynamic> j) => SystemResources(
    uptime: j['uptime'] ?? '', loadAverage: List<double>.from((j['load_average'] ?? []).map((e) => (e as num).toDouble())),
    memTotalMb: j['memory_total_mb'] ?? 0, memUsedMb: j['memory_used_mb'] ?? 0,
    memPercent: (j['memory_percent'] ?? 0).toDouble(), cpuCount: j['cpu_count'] ?? 1,
  );
}

class DashboardStatus {
  final InterfaceInfo vpn, lan;
  final Map<String, bool> services;
  final int domainsCount, ipsetEntries;
  final SystemResources resources;
  final Map<String, dynamic>? connectivity;

  DashboardStatus({required this.vpn, required this.lan, required this.services,
    required this.domainsCount, required this.ipsetEntries, required this.resources, this.connectivity});

  factory DashboardStatus.fromJson(Map<String, dynamic> j) => DashboardStatus(
    vpn: InterfaceInfo.fromJson(j['vpn']), lan: InterfaceInfo.fromJson(j['lan']),
    services: Map<String, bool>.from(j['services'] ?? {}),
    domainsCount: j['domains_count'] ?? 0, ipsetEntries: j['ipset_entries'] ?? 0,
    resources: SystemResources.fromJson(j['resources']),
    connectivity: j['connectivity'] as Map<String, dynamic>?,
  );
}

class DomainGroup {
  final String name;
  final List<String> domains;
  DomainGroup({required this.name, required this.domains});
  factory DomainGroup.fromJson(Map<String, dynamic> j) => DomainGroup(
    name: j['name'] ?? '', domains: List<String>.from(j['domains'] ?? []),
  );
}

class ServiceInfo {
  final String name, description, state;
  final bool active, enabled;
  ServiceInfo({required this.name, this.description = '', required this.state, required this.active, required this.enabled});
  factory ServiceInfo.fromJson(Map<String, dynamic> j) => ServiceInfo(
    name: j['name'] ?? '', description: j['description'] ?? '', state: j['state'] ?? '',
    active: j['active'] ?? false, enabled: j['enabled'] ?? false,
  );
}

class NetworkFile {
  final String name, filename, description;
  final int entryCount;
  final List<String> entries;
  NetworkFile({required this.name, required this.filename, required this.description, required this.entryCount, required this.entries});
  factory NetworkFile.fromJson(Map<String, dynamic> j) => NetworkFile(
    name: j['name'] ?? '', filename: j['filename'] ?? '', description: j['description'] ?? '',
    entryCount: j['entry_count'] ?? 0, entries: List<String>.from(j['entries'] ?? []),
  );
}

class IpsetInfo {
  final String name, type;
  final int entries, maxEntries, memoryBytes;
  IpsetInfo({required this.name, required this.type, required this.entries, required this.maxEntries, required this.memoryBytes});
  factory IpsetInfo.fromJson(Map<String, dynamic> j) => IpsetInfo(
    name: j['name'] ?? '', type: j['type'] ?? '', entries: j['entries'] ?? 0,
    maxEntries: j['max_entries'] ?? 0, memoryBytes: j['memory_bytes'] ?? 0,
  );
}

class RouteInfo {
  final String destination, device;
  final String? gateway;
  RouteInfo({required this.destination, required this.device, this.gateway});
  factory RouteInfo.fromJson(Map<String, dynamic> j) => RouteInfo(
    destination: j['destination'] ?? '', device: j['device'] ?? '', gateway: j['gateway'],
  );
}

String formatBytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1048576) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  if (bytes < 1073741824) return '${(bytes / 1048576).toStringAsFixed(1)} MB';
  return '${(bytes / 1073741824).toStringAsFixed(1)} GB';
}
