import 'package:flutter_test/flutter_test.dart';

import 'package:vpngateway_admin/main.dart';

void main() {
  testWidgets('renders the gateway navigation shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const VpnGatewayApp());

    expect(find.text('Dashboard'), findsWidgets);
    expect(find.text('Domains'), findsOneWidget);
    expect(find.text('Networks'), findsOneWidget);
    expect(find.text('Routing'), findsOneWidget);
    expect(find.text('More'), findsOneWidget);
  });
}
