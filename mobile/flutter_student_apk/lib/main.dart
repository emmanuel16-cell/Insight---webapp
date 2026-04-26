import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'login_page.dart';
import 'dashboard_page.dart';
import 'api_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const InSightApp());
}

class InSightApp extends StatelessWidget {
  const InSightApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'InSight Student',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF2EC4B6),
          primary: const Color(0xFF2EC4B6),
          secondary: const Color(0xFF219EBC),
        ),
        useMaterial3: true,
      ),
      home: const LoginPage(),
    );
  }
}
