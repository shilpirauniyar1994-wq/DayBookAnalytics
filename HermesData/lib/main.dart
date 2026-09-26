import 'dart:convert';
import 'dart:typed_data';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:intl/intl.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';
import 'package:flutter/services.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:image_picker/image_picker.dart';
import 'package:share_plus/share_plus.dart';
import 'package:path_provider/path_provider.dart';
import 'package:cached_network_image/cached_network_image.dart';

// --- CONFIGURATION ---
const String supabaseUrl = 'https://ktlzbplvxmpxzbbsxbid.supabase.co';
const String supabaseKey = 'sb_publishable_PVwz5LDTZzJr9kqbgD2A3g_mdMZajai';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Supabase.initialize(url: supabaseUrl, anonKey: supabaseKey);
  runApp(const MaterialApp(
    debugShowCheckedModeBanner: false,
    title: "Khelauna",
    home: BafaCatalogueV2(),
  ));
}

class BafaCatalogueV2 extends StatefulWidget {
  const BafaCatalogueV2({super.key});
  @override
  _BafaCatalogueV2State createState() => _BafaCatalogueV2State();
}

class _BafaCatalogueV2State extends State<BafaCatalogueV2> {
  final String sheetUrl =
      'https://docs.google.com/spreadsheets/d/e/2PACX-1vRxJeOQiUDMDIeKI1FShWu7SNw0EuQs2gfDZ6ulfPDlF7RFRCb0jvIghjUkPeA965yec9swKa_5ibG5/pub?gid=25486059&single=true&output=csv';

  // --- STATE VARIABLES ---
  List<Map<String, dynamic>> allProducts = [];
  List<Map<String, dynamic>> filteredProducts = [];
  Map<String, dynamic> cloudData = {};
  Map<String, TextEditingController> qtyControllers = {};
  Set<String> selectedProductIds = {};

  // UI State
  bool isLoading = true;
  int adminLevel = 0; // 0: User, 1: Admin, 2: Super Admin
  String searchQuery = "";
  final TextEditingController _searchController = TextEditingController();

  // Cached Tag Data
  List<String> topTags = [];
  List<String> sidebarTags = [];

  @override
  void initState() {
    super.initState();
    _loadSheetData();
    _listenToCloud();
  }

  @override
  void dispose() {
    for (var c in qtyControllers.values) c.dispose();
    _searchController.dispose();
    super.dispose();
  }

  // --- DATA LOADING & SYNC ---

  /// Listen to real-time updates from Supabase
  void _listenToCloud() {
    Supabase.instance.client
        .from('products')
        .stream(primaryKey: ['id']).listen((data) {
      Map<String, dynamic> temp = {};
      for (var row in data) {
        temp[row['id']] = row;
      }
      if (mounted) {
        setState(() {
          cloudData = temp;
          _calculateTags();
          _refreshFilter();
        });
      }
    });
  }

  /// Load data from Google Sheet (CSV)
  Future<void> _loadSheetData() async {
    setState(() => isLoading = true);
    try {
      final response = await http.get(Uri.parse(sheetUrl));
      if (response.statusCode == 200) {
        List<String> rows = response.body.replaceAll('\r', '').split('\n');
        List<Map<String, dynamic>> temp = [];
        List<String> unitCosts = [];

        for (var i = 1; i < rows.length; i++) {
          var columns = rows[i].split(',');
          if (columns.length >= 2) {
            String id = columns[0].trim();
            if (id.isEmpty) continue;
            String stock = columns[1].trim();
            String unitCost = columns.length > 2 ? columns[2].trim() : "0";
            if (unitCost.isEmpty) unitCost = "0";

            temp.add({'id': id, 'stock': stock, 'unitCost': unitCost});
            unitCosts.add(unitCost);
            qtyControllers.putIfAbsent(id, () => TextEditingController());
          }
        }

        // Update local state and hide loading
        setState(() {
          allProducts = temp;
          _refreshFilter();
          isLoading = false;
        });

        // Sync costs to cloud in background if sheet changed
        String currentHash = unitCosts.join(',').hashCode.toString();
        SharedPreferences prefs = await SharedPreferences.getInstance();
        if (prefs.getString('sheet_hash') != currentHash) {
          _syncCostsToCloud(temp, currentHash);
        }
      }
    } catch (e) {
      if (kDebugMode) print("Sheet load error: $e");
    } finally {
      if (mounted) setState(() => isLoading = false);
    }
  }

  /// Sync product costs to Supabase in batches
  Future<void> _syncCostsToCloud(
      List<Map<String, dynamic>> products, String hash) async {
    try {
      final data = products
          .map((p) => {'id': p['id'], 'price': p['unitCost']})
          .toList();
      // Batch upsert in chunks of 200
      for (var i = 0; i < data.length; i += 200) {
        final end = (i + 200 > data.length) ? data.length : i + 200;
        await Supabase.instance.client.from('products').upsert(data.sublist(i, end));
      }
      SharedPreferences prefs = await SharedPreferences.getInstance();
      await prefs.setString('sheet_hash', hash);
    } catch (e) {
      if (kDebugMode) print("Sync error: $e");
    }
  }

  /// Save single product edits to cloud
  Future<void> _saveProductToCloud(
      String id, String tags, String sellingPrice) async {
    try {
      await Supabase.instance.client.from('products').upsert({
        'id': id,
        'tags': tags,
        'selling_price': sellingPrice,
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text("Cloud Updated"),
          duration: Duration(milliseconds: 500),
        ));
      }
    } catch (e) {
      if (kDebugMode) print("Cloud save error: $e");
    }
  }

  /// Upload photo to Supabase storage
  Future<void> _uploadPhoto(String id) async {
    final picker = ImagePicker();
    final XFile? image =
        await picker.pickImage(source: ImageSource.gallery, imageQuality: 50);
    if (image == null) return;

    setState(() => isLoading = true);
    try {
      final bytes = await image.readAsBytes();
      final fileName = '${id}_${DateTime.now().millisecondsSinceEpoch}.jpg';
      await Supabase.instance.client.storage
          .from('product_photos')
          .uploadBinary(fileName, bytes,
              fileOptions: const FileOptions(upsert: true));

      final String publicUrl = Supabase.instance.client.storage
          .from('product_photos')
          .getPublicUrl(fileName);

      await Supabase.instance.client.from('products').upsert({
        'id': id,
        'image_url': publicUrl,
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text("Photo Uploaded Successfully!")));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text("Upload error: $e"), backgroundColor: Colors.red));
      }
    } finally {
      if (mounted) setState(() => isLoading = false);
    }
  }

  // --- LOGIC & HELPERS ---

  /// Calculate tags and counts for sidebar and top bar
  void _calculateTags() {
    Map<String, int> counts = {};
    cloudData.forEach((key, val) {
      String t = (val['tags'] ?? "").toString();
      for (var s in t.split(';')) {
        String tag = s.trim().toUpperCase();
        if (tag.isNotEmpty) {
          counts[tag] = (counts[tag] ?? 0) + 1;
        }
      }
    });

    topTags = (counts.keys.toList()
      ..sort((a, b) => counts[b]!.compareTo(counts[a]!)))
        .take(10)
        .toList();
    sidebarTags = counts.keys.toList()..sort();
  }

  /// Filter products based on search query
  void _refreshFilter() {
    String q = searchQuery.toLowerCase();
    filteredProducts = allProducts.where((p) {
      String id = p['id'].toLowerCase();
      String tags =
          (cloudData[p['id']]?['tags'] ?? "").toString().toLowerCase();
      return id.contains(q) || tags.contains(q);
    }).toList();
  }

  /// Toggle selection of all items in the current filtered view
  void _toggleSelectAll() {
    setState(() {
      bool allSelected = filteredProducts.isNotEmpty &&
          filteredProducts.every((p) => selectedProductIds.contains(p['id']));

      if (allSelected) {
        for (var p in filteredProducts) {
          selectedProductIds.remove(p['id']);
        }
      } else {
        for (var p in filteredProducts) {
          selectedProductIds.add(p['id']);
        }
      }
    });
  }

  /// Fetch image bytes from cloud or local assets
  Future<Uint8List?> _getImageBytes(String id) async {
    // 1. Try Cloud URL
    String? cloudUrl = cloudData[id]?['image_url'];
    if (cloudUrl != null && cloudUrl.isNotEmpty) {
      try {
        final r = await http.get(Uri.parse(cloudUrl));
        if (r.statusCode == 200) return r.bodyBytes;
      } catch (e) {
        if (kDebugMode) print("Cloud image error for $id: $e");
      }
    }

    // 2. Try Local Assets (various extensions and cases)
    final exts = ['.jpg', '.jpeg', '.JPG', '.png', '.PNG', '.JPEG'];
    for (var ext in exts) {
      final paths = [
        "assets/images/$id$ext",
        "assets/images/${id.toUpperCase()}$ext",
        "assets/images/${id.toLowerCase()}$ext"
      ];
      for (var path in paths) {
        try {
          ByteData data = await rootBundle.load(path);
          return data.buffer.asUint8List();
        } catch (_) {}
      }
    }
    return null;
  }

  // --- UI DIALOGS ---

  /// Show large photo view
  void _showEnlargedPhoto(String id) {
    showDialog(
      context: context,
      builder: (ctx) => Dialog(
        backgroundColor: Colors.transparent,
        insetPadding: const EdgeInsets.all(10),
        child: Stack(
          alignment: Alignment.center,
          children: [
            Container(
              width: double.infinity,
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
              ),
              padding: const EdgeInsets.all(10),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(id,
                      style: const TextStyle(
                          fontWeight: FontWeight.bold, fontSize: 18)),
                  const SizedBox(height: 10),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: InteractiveViewer(
                      child: _buildImage(id, highRes: true),
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextButton(
                    onPressed: () => Navigator.pop(ctx),
                    child: const Text("CLOSE"),
                  ),
                ],
              ),
            ),
            Positioned(
              top: 10,
              right: 10,
              child: IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(ctx),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Edit product tags and price
  void _showProductEditor(String productId, Set<String> pool, int currentLevel) {
    List<String> currentTags = (cloudData[productId]?['tags'] ?? "")
        .toString()
        .split(';')
        .where((t) => t.trim().isNotEmpty)
        .toList();
    final TextEditingController _priceController = TextEditingController(
        text: (cloudData[productId]?['selling_price'] ?? "").toString());
    final TextEditingController _tagInputController = TextEditingController();
    final FocusNode _tagFocus = FocusNode();
    int selectedIndex = -1;

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (context, setDialogState) {
          List<String> suggestions = pool
              .where((t) =>
                  t.toLowerCase().contains(_tagInputController.text.toLowerCase()) &&
                  !currentTags.contains(t))
              .toList();

          void addTag(String tag) {
            String cleanTag = tag.trim().toUpperCase();
            if (cleanTag.isNotEmpty && !currentTags.contains(cleanTag)) {
              setDialogState(() {
                currentTags.add(cleanTag);
                _tagInputController.clear();
                selectedIndex = -1;
              });
              _tagFocus.requestFocus();
            }
          }

          return AlertDialog(
            title: Text("Edit: $productId",
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            content: SizedBox(
              width: 350,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (currentLevel >= 1) ...[
                    const Text("SELLING PRICE (RS)",
                        style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold)),
                    TextField(
                      controller: _priceController,
                      decoration: const InputDecoration(
                          hintText: "Enter Selling Price...",
                          border: OutlineInputBorder()),
                      keyboardType: TextInputType.number,
                    ),
                    const SizedBox(height: 15),
                  ],
                  if (currentLevel == 2) ...[
                    Text("Cost Price: Rs ${(cloudData[productId]?['price'] ?? "")}",
                        style: const TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.bold,
                            color: Colors.redAccent)),
                    const SizedBox(height: 15),
                  ],
                  const Text("TAGS",
                      style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold)),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: currentTags
                        .map((tag) => Chip(
                              label: Text(tag, style: const TextStyle(fontSize: 10)),
                              onDeleted: () {
                                setDialogState(() => currentTags.remove(tag));
                                _tagFocus.requestFocus();
                              },
                              visualDensity: VisualDensity.compact,
                            ))
                        .toList(),
                  ),
                  const SizedBox(height: 10),
                  KeyboardListener(
                    focusNode: FocusNode(),
                    onKeyEvent: (event) {
                      if (event is KeyDownEvent) {
                        if (event.logicalKey == LogicalKeyboardKey.arrowDown) {
                          setDialogState(() => selectedIndex = (selectedIndex + 1)
                              .clamp(-1, suggestions.length - 1));
                        } else if (event.logicalKey == LogicalKeyboardKey.arrowUp) {
                          setDialogState(() => selectedIndex = (selectedIndex - 1)
                              .clamp(-1, suggestions.length - 1));
                        } else if (event.logicalKey == LogicalKeyboardKey.enter) {
                          if (selectedIndex != -1) {
                            addTag(suggestions[selectedIndex]);
                          } else if (_tagInputController.text.isNotEmpty) {
                            addTag(_tagInputController.text);
                          }
                        }
                      }
                    },
                    child: TextField(
                      controller: _tagInputController,
                      focusNode: _tagFocus,
                      autofocus: true,
                      decoration: const InputDecoration(
                        hintText: "Add Tag...",
                        border: OutlineInputBorder(),
                        isDense: true,
                      ),
                      onChanged: (v) => setDialogState(() => selectedIndex = -1),
                      onSubmitted: (value) => addTag(value),
                    ),
                  ),
                  if (_tagInputController.text.isNotEmpty && suggestions.isNotEmpty)
                    Container(
                      height: 100,
                      margin: const EdgeInsets.only(top: 4),
                      decoration:
                          BoxDecoration(border: Border.all(color: Colors.grey[200]!)),
                      child: ListView.builder(
                        itemCount: suggestions.length,
                        itemBuilder: (ctx, i) => ListTile(
                          title: Text(suggestions[i],
                              style: const TextStyle(fontSize: 11)),
                          dense: true,
                          selected: i == selectedIndex,
                          selectedTileColor: Colors.blueGrey[50],
                          onTap: () => addTag(suggestions[i]),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text("Cancel")),
              ElevatedButton(
                onPressed: () {
                  _saveProductToCloud(
                      productId, currentTags.join(';'), _priceController.text);
                  Navigator.pop(context);
                },
                child: const Text("Save"),
              ),
            ],
          );
        },
      ),
    );
  }

  // --- PDF EXPORT ---

  /// Generate and share Order PDF
  Future<void> _shareOrder() async {
    final items = allProducts
        .where((p) => selectedProductIds.contains(p['id']))
        .toList();
    if (items.isEmpty) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text("No items selected!")));
      return;
    }

    setState(() => isLoading = true);
    try {
      final pdf = pw.Document();
      final font = await PdfGoogleFonts.nunitoRegular();

      // Parallel Image Fetch
      final Map<String, Uint8List?> itemImages = {};
      await Future.wait(items.map((it) async {
        itemImages[it['id']] = await _getImageBytes(it['id']);
      }));

      // Pagination: 12 items per page
      for (var i = 0; i < items.length; i += 12) {
        final chunk = items.sublist(
            i, i + 12 > items.length ? items.length : i + 12);
        List<pw.Widget> pageWidgets = [];

        for (var it in chunk) {
          final img = itemImages[it['id']];
          String price =
              (cloudData[it['id']]?['selling_price'] ?? "").toString();
          String q = qtyControllers[it['id']]?.text ?? "0";

          pageWidgets.add(pw.Container(
            width: 175,
            padding: const pw.EdgeInsets.all(4),
            decoration: pw.BoxDecoration(
                border: pw.Border.all(color: PdfColors.grey300, width: 0.5)),
            child: pw.Column(
              crossAxisAlignment: pw.CrossAxisAlignment.start,
              children: [
                pw.Container(
                  height: 120,
                  width: double.infinity,
                  child: img != null
                      ? pw.Image(pw.MemoryImage(img), fit: pw.BoxFit.contain)
                      : pw.Center(
                          child:
                              pw.Text("NO PHOTO", style: const pw.TextStyle(fontSize: 8))),
                ),
                pw.SizedBox(height: 4),
                pw.Text(it['id'],
                    style: pw.TextStyle(
                        font: font,
                        fontWeight: pw.FontWeight.bold,
                        fontSize: 9),
                    maxLines: 2),
                if (price.isNotEmpty)
                  pw.Text("Price: Rs $price",
                      style: pw.TextStyle(
                          font: font,
                          fontSize: 8,
                          fontWeight: pw.FontWeight.bold)),
                pw.Text("ORDER: $q",
                    style: pw.TextStyle(
                        font: font,
                        fontSize: 10,
                        fontWeight: pw.FontWeight.bold,
                        color: PdfColors.orange900)),
              ],
            ),
          ));
        }

        pdf.addPage(pw.Page(
          pageFormat: PdfPageFormat.a4,
          margin: const pw.EdgeInsets.all(15),
          build: (pw.Context context) => pw.Column(
            children: [
              pw.Header(
                  level: 0,
                  child: pw.Text("Order - Nepal Khelauna Udhyog",
                      style: pw.TextStyle(font: font, fontSize: 14))),
              pw.SizedBox(height: 10),
              pw.Wrap(spacing: 8, runSpacing: 8, children: pageWidgets),
            ],
          ),
        ));
      }

      final bytes = await pdf.save();
      final tempDir = await getTemporaryDirectory();
      final file = await File(
              '${tempDir.path}/Order_${DateTime.now().millisecondsSinceEpoch}.pdf')
          .create();
      await file.writeAsBytes(bytes);
      await Share.shareXFiles([XFile(file.path)],
          text: 'Order from Nepal Khelauna Udhyog');
    } catch (e) {
      if (kDebugMode) print("PDF error: $e");
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text("PDF Generation error: $e")));
      }
    } finally {
      if (mounted) setState(() => isLoading = false);
    }
  }

  // --- IMAGE WIDGETS ---

  Widget _buildImage(String id, {bool highRes = false}) {
    String? cloudUrl = cloudData[id]?['image_url'];
    if (cloudUrl != null && cloudUrl.isNotEmpty) {
      return CachedNetworkImage(
        imageUrl: cloudUrl,
        fit: BoxFit.contain,
        placeholder: (c, u) => const Center(
          child: SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 1),
          ),
        ),
        errorWidget: (c, u, e) => _buildLocalFallback(id, 0, highRes),
      );
    }
    return _buildLocalFallback(id, 0, highRes);
  }

  Widget _buildLocalFallback(String id, int index, bool highRes) {
    final exts = ['.jpg', '.jpeg', '.JPG'];
    final paths = [
      "assets/images/$id${exts[index % 3]}",
      "assets/images/${id.toUpperCase()}${exts[index % 3]}"
    ];
    if (index >= 6) {
      return Center(
        child: Icon(Icons.toys,
            color: Colors.grey, size: highRes ? 50 : 16),
      );
    }
    return Image.asset(
      paths[index % 2],
      fit: BoxFit.contain,
      errorBuilder: (c, e, s) => _buildLocalFallback(id, index + 1, highRes),
    );
  }

  // --- BUILD METHOD ---

  @override
  Widget build(BuildContext context) {
    bool isAllSelected = filteredProducts.isNotEmpty &&
        filteredProducts.every((p) => selectedProductIds.contains(p['id']));

    return Scaffold(
      backgroundColor: Colors.grey[50],
      appBar: AppBar(
        title: const Text("NEPAL KHELAUNA UDHYOG",
            style: TextStyle(
                fontWeight: FontWeight.w900, fontSize: 16, color: Colors.blueGrey)),
        backgroundColor: Colors.white,
        elevation: 0.5,
        actions: [
          TextButton.icon(
            icon: Icon(
                isAllSelected ? Icons.check_circle : Icons.circle_outlined,
                size: 16,
                color: Colors.blueAccent),
            label: Text(isAllSelected ? "DESELECT ALL" : "SELECT ALL",
                style: const TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: Colors.blueAccent)),
            onPressed: _toggleSelectAll,
          ),
          const SizedBox(width: 10),
          Stack(
            alignment: Alignment.center,
            children: [
              IconButton(
                  icon: const Icon(Icons.share, color: Colors.blueAccent, size: 22),
                  onPressed: _shareOrder),
              if (selectedProductIds.isNotEmpty)
                Positioned(
                  top: 8,
                  right: 8,
                  child: CircleAvatar(
                    radius: 6,
                    backgroundColor: Colors.red,
                    child: Text(selectedProductIds.length.toString(),
                        style: const TextStyle(fontSize: 6, color: Colors.white)),
                  ),
                ),
            ],
          ),
          IconButton(
              icon: const Icon(Icons.refresh, color: Colors.blueGrey, size: 20),
              onPressed: _loadSheetData),
        ],
      ),
      drawer: Drawer(
        child: Column(
          children: [
            DrawerHeader(
              decoration: BoxDecoration(
                  color: adminLevel == 2
                      ? Colors.redAccent[700]
                      : adminLevel == 1
                          ? Colors.orangeAccent[700]
                          : Colors.blueGrey[900]),
              child: const Center(
                child: Text("NEPAL KHELAUNA",
                    style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 20)),
              ),
            ),
            ListTile(
              leading: Icon(
                  adminLevel > 0 ? Icons.admin_panel_settings : Icons.person_outline),
              title: Text(adminLevel == 2
                  ? "Logout Super Admin"
                  : adminLevel == 1
                      ? "Logout Admin"
                      : "Login as Admin"),
              onTap: () {
                if (adminLevel > 0) {
                  setState(() {
                    adminLevel = 0;
                    selectedProductIds.clear();
                  });
                  Navigator.pop(context);
                  return;
                }
                TextEditingController _pc = TextEditingController();
                showDialog(
                  context: context,
                  builder: (ctx) => AlertDialog(
                    title: const Text("Admin Login"),
                    content: TextField(
                        controller: _pc,
                        obscureText: true,
                        autofocus: true,
                        decoration: const InputDecoration(hintText: "Password"),
                        onSubmitted: (v) {
                          final pass = v.trim();
                          if (pass == "bafa123") {
                            setState(() => adminLevel = 1);
                          } else if (pass == "superbafa") {
                            setState(() => adminLevel = 2);
                          }
                          Navigator.pop(context);
                        }),
                    actions: [
                      TextButton(
                        onPressed: () {
                          final pass = _pc.text.trim();
                          if (pass == "bafa123") {
                            setState(() => adminLevel = 1);
                          } else if (pass == "superbafa") {
                            setState(() => adminLevel = 2);
                          }
                          Navigator.pop(context);
                        },
                        child: const Text("Login"),
                      ),
                    ],
                  ),
                );
              },
            ),
            const Divider(),
            Expanded(
              child: ListView(
                children: [
                  ListTile(
                    leading: const Icon(Icons.grid_view, size: 18),
                    title: const Text("All Products"),
                    onTap: () {
                      setState(() {
                        searchQuery = "";
                        _searchController.clear();
                        _refreshFilter();
                      });
                      Navigator.pop(context);
                    },
                  ),
                  ...sidebarTags.map((tag) => ListTile(
                        dense: true,
                        leading: const Icon(Icons.label_outline, size: 16),
                        title: Text(tag,
                            style: const TextStyle(fontWeight: FontWeight.w500)),
                        onTap: () {
                          setState(() {
                            searchQuery = tag;
                            _searchController.text = tag;
                            _refreshFilter();
                            Navigator.pop(context);
                          });
                        },
                      )),
                ],
              ),
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 8),
            color: Colors.white,
            child: TextField(
              controller: _searchController,
              decoration: InputDecoration(
                hintText: "Search Product ID or Tags...",
                prefixIcon: const Icon(Icons.search, size: 20),
                fillColor: Colors.grey[100],
                filled: true,
                isDense: true,
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide.none),
              ),
              onChanged: (v) {
                setState(() {
                  searchQuery = v;
                  _refreshFilter();
                });
              },
            ),
          ),
          if (topTags.isNotEmpty)
            Container(
              height: 40,
              color: Colors.white,
              child: ListView.builder(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                itemCount: topTags.length,
                itemBuilder: (ctx, i) => Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ActionChip(
                    label: Text(topTags[i],
                        style: const TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.bold,
                            color: Colors.blueGrey)),
                    backgroundColor: Colors.blueGrey[50]!.withOpacity(0.5),
                    onPressed: () {
                      setState(() {
                        _searchController.text = topTags[i];
                        searchQuery = topTags[i];
                        _refreshFilter();
                      });
                    },
                  ),
                ),
              ),
            ),
          const Divider(height: 1),
          Expanded(
            child: isLoading
                ? const Center(child: CircularProgressIndicator())
                : GridView.builder(
                    padding: const EdgeInsets.all(10),
                    gridDelegate:
                        const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 4,
                      childAspectRatio: 0.58,
                      crossAxisSpacing: 10,
                      mainAxisSpacing: 10,
                    ),
                    itemCount: filteredProducts.length,
                    itemBuilder: (ctx, i) {
                      final p = filteredProducts[i];
                      String id = p['id'];
                      String tags = (cloudData[id]?['tags'] ?? "").toString();
                      String sellingPrice =
                          (cloudData[id]?['selling_price'] ?? "").toString();
                      String costPrice =
                          (cloudData[id]?['price'] ?? "").toString();
                      bool isSelected = selectedProductIds.contains(id);
                      final controller = qtyControllers[id]!;

                      return Container(
                        key: ValueKey(id),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(
                              color: isSelected
                                  ? Colors.blueAccent
                                  : Colors.transparent,
                              width: 1.5),
                          boxShadow: [
                            BoxShadow(
                                color: Colors.black.withOpacity(0.03),
                                blurRadius: 5,
                                spreadRadius: 1)
                          ],
                        ),
                        child: InkWell(
                          onTap: () {
                            if (adminLevel > 0) {
                              _showProductEditor(id, sidebarTags.toSet(), adminLevel);
                            } else {
                              _showEnlargedPhoto(id);
                            }
                          },
                          onLongPress: () {
                            if (adminLevel > 0) _uploadPhoto(id);
                          },
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Expanded(
                                child: Stack(
                                  children: [
                                    Container(
                                      width: double.infinity,
                                      padding: const EdgeInsets.all(4),
                                      child: ClipRRect(
                                        borderRadius: BorderRadius.circular(4),
                                        child: _buildImage(id),
                                      ),
                                    ),
                                    Positioned(
                                      top: 0,
                                      right: 0,
                                      child: Transform.scale(
                                        scale: 0.7,
                                        child: Checkbox(
                                          value: isSelected,
                                          activeColor: Colors.blueAccent,
                                          materialTapTargetSize:
                                              MaterialTapTargetSize.shrinkWrap,
                                          onChanged: (val) {
                                            setState(() {
                                              if (val == true) {
                                                selectedProductIds.add(id);
                                              } else {
                                                selectedProductIds.remove(id);
                                              }
                                            });
                                          },
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              Padding(
                                padding: const EdgeInsets.fromLTRB(6, 2, 6, 6),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      id,
                                      style: const TextStyle(
                                          fontWeight: FontWeight.bold,
                                          fontSize: 9,
                                          color: Colors.black87),
                                      maxLines: 2,
                                      overflow: TextOverflow.visible,
                                    ),
                                    if (sellingPrice.isNotEmpty)
                                      Text(
                                        "Rs $sellingPrice",
                                        style: const TextStyle(
                                            fontSize: 10,
                                            fontWeight: FontWeight.w900,
                                            color: Colors.blueGrey),
                                      ),
                                    if (costPrice.isNotEmpty && adminLevel == 2)
                                      Text(
                                        "Cost: Rs $costPrice",
                                        style: const TextStyle(
                                            fontSize: 8,
                                            fontWeight: FontWeight.w600,
                                            color: Colors.redAccent),
                                      ),
                                    if (adminLevel > 0 && tags.isNotEmpty)
                                      Text(
                                        tags.replaceAll(';', ' • '),
                                        style: const TextStyle(
                                            fontSize: 6,
                                            color: Colors.blueGrey,
                                            fontStyle: FontStyle.italic),
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    if (adminLevel > 0)
                                      Text(
                                        "Stock: ${p['stock']}",
                                        style: const TextStyle(
                                            fontSize: 8,
                                            color: Colors.green,
                                            fontWeight: FontWeight.bold),
                                      ),
                                    const SizedBox(height: 4),
                                    SizedBox(
                                      height: 22,
                                      child: TextField(
                                        controller: controller,
                                        keyboardType: TextInputType.number,
                                        style: const TextStyle(
                                            fontSize: 10,
                                            fontWeight: FontWeight.bold,
                                            color: Colors.orange),
                                        decoration: InputDecoration(
                                          hintText: "Order",
                                          isDense: true,
                                          contentPadding:
                                              const EdgeInsets.symmetric(
                                                  horizontal: 4),
                                          fillColor: Colors.orange[50],
                                          filled: true,
                                          border: OutlineInputBorder(
                                              borderRadius:
                                                  BorderRadius.circular(4),
                                              borderSide: BorderSide.none),
                                        ),
                                        onChanged: (val) {
                                          setState(() {
                                            if (val.isNotEmpty && val != "0") {
                                              selectedProductIds.add(id);
                                            } else {
                                              selectedProductIds.remove(id);
                                            }
                                          });
                                        },
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
