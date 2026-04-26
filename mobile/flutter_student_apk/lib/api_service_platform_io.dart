import 'dart:io';
import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';
import 'package:cookie_jar/cookie_jar.dart';
import 'package:path_provider/path_provider.dart';
import 'package:flutter/foundation.dart';

String getDefaultBaseUrl() {
  // Default fallback for local testing on mobile emulator/device
  return 'http://172.30.128.1:8000';
}

Future<void> configureDioForPlatform(Dio dio) async {
  final appDocDir = await getApplicationDocumentsDirectory();
  final appDocPath = appDocDir.path;
  final cookieJar = PersistCookieJar(
    ignoreExpires: false,
    storage: FileStorage("$appDocPath/.cookies/"),
  );
  dio.interceptors.add(CookieManager(cookieJar));
}

Future<void> discoverServerForPlatform({
  required String currentBaseUrl,
  required void Function(String url) onUrlDiscovered,
}) async {
  try {
    RawDatagramSocket.bind(InternetAddress.anyIPv4, 8888).then((RawDatagramSocket socket) {
      if (kDebugMode) print('📡 Listening for server discovery on port 8888...');
      
      socket.listen((RawSocketEvent event) {
        if (event == RawSocketEvent.read) {
          Datagram? dg = socket.receive();
          if (dg == null) return;

          String message = utf8.decode(dg.data);
          if (message.startsWith("INSIGHT_SERVER_IP:")) {
            String ip = message.split(":")[1];
            String newUrl = "http://$ip:8000";
            
            if (newUrl != currentBaseUrl) {
              onUrlDiscovered(newUrl);
            }
            socket.close();
          }
        }
      });

      Future.delayed(const Duration(seconds: 30), () {
        socket.close();
      });
    });
  } catch (e) {
    if (kDebugMode) print("⚠️ Discovery error: $e");
  }
}
