import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;

String getDefaultBaseUrl() {
  if (kIsWeb) {
    // On web, default to the current host
    final Uri uri = Uri.parse(html.window.location.href);
    // If we're running on a dev server (like localhost:5000), 
    // we might still need to point to the backend (localhost:8000)
    // but usually, if deployed, it's the same origin.
    if (uri.host == 'localhost' || uri.host == '127.0.0.1') {
       return 'http://${uri.host}:8000';
    }
    return '${uri.scheme}://${uri.host}${uri.port != 80 && uri.port != 443 ? ":${uri.port}" : ""}';
  }
  return 'http://localhost:8000';
}

Future<void> configureDioForPlatform(Dio dio) async {
  // Browsers handle cookies automatically via withCredentials
  dio.options.extra['withCredentials'] = true;
}

Future<void> discoverServerForPlatform({
  required String currentBaseUrl,
  required void Function(String url) onUrlDiscovered,
}) async {
  // UDP discovery is not possible in the browser
  if (kDebugMode) print("🌐 Web platform: Skipping UDP discovery.");
  return;
}
