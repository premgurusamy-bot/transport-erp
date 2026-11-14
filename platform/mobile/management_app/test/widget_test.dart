import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grl_management/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('login screen renders when signed out', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(const ManagementApp());
    expect(find.text('Sign in'), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(3));
  });

  test('inr formats money', () {
    expect(inr('1234.5'), '₹ 1234.50');
    expect(inr(null), '—');
  });
}
