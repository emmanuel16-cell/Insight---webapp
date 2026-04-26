import 'package:dio/dio.dart';

String getDefaultBaseUrl() => throw UnsupportedError('Cannot get default base URL without platform implementation');

Future<void> configureDioForPlatform(Dio dio) => throw UnsupportedError('Cannot configure Dio without platform implementation');

Future<void> discoverServerForPlatform({
  required String currentBaseUrl,
  required void Function(String url) onUrlDiscovered,
}) => throw UnsupportedError('Cannot discover server without platform implementation');
