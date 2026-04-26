import 'package:dio/dio.dart';

import 'api_service_platform_stub.dart'
    if (dart.library.html) 'api_service_platform_web.dart'
    if (dart.library.io) 'api_service_platform_io.dart' as platform;

String getDefaultBaseUrl() => platform.getDefaultBaseUrl();

Future<void> configureDioForPlatform(Dio dio) => platform.configureDioForPlatform(dio);

Future<void> discoverServerForPlatform({
  required String currentBaseUrl,
  required void Function(String url) onUrlDiscovered,
}) {
  return platform.discoverServerForPlatform(
    currentBaseUrl: currentBaseUrl,
    onUrlDiscovered: onUrlDiscovered,
  );
}
