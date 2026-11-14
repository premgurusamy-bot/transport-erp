// G ROAD LINES Management App: dashboard, approvals, control tower, trips, alerts.
// Every action goes through the same backend permission and maker-checker controls as the ERP.
import 'package:flutter/material.dart';

import 'api.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.instance.load();
  runApp(const ManagementApp());
}

class ManagementApp extends StatelessWidget {
  const ManagementApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'GRL Management',
        theme: ThemeData(colorSchemeSeed: const Color(0xFF0B4F8A), useMaterial3: true),
        darkTheme: ThemeData(colorSchemeSeed: const Color(0xFF0B4F8A), brightness: Brightness.dark, useMaterial3: true),
        home: Api.instance.token == null ? const LoginPage() : const Home(),
      );
}

String inr(dynamic v) => v == null ? '—' : '₹ ${double.tryParse('$v')?.toStringAsFixed(2) ?? v}';

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});
  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final url = TextEditingController(text: Api.instance.baseUrl.isEmpty ? 'https://' : Api.instance.baseUrl);
  final id = TextEditingController();
  final pw = TextEditingController();
  String? msg;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('G ROAD LINES Management')),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          TextField(controller: url, decoration: const InputDecoration(labelText: 'Server address')),
          TextField(controller: id, decoration: const InputDecoration(labelText: 'Email or phone')),
          TextField(controller: pw, obscureText: true, decoration: const InputDecoration(labelText: 'Password')),
          const SizedBox(height: 12),
          FilledButton(
              onPressed: () async {
                await Api.instance.saveSession(url.text.trim(), null);
                try {
                  final r = await Api.instance.post('/auth/login', {'identifier': id.text.trim(), 'password': pw.text, 'device': 'android-management'});
                  await Api.instance.saveSession(url.text.trim(), r['token']);
                  if (context.mounted) Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const Home()));
                } on ApiException catch (e) {
                  setState(() => msg = e.message);
                }
              },
              child: const Text('Sign in')),
          if (msg != null) Text(msg!),
        ]),
      );
}

class Home extends StatefulWidget {
  const Home({super.key});
  @override
  State<Home> createState() => _HomeState();
}

class _HomeState extends State<Home> {
  int tab = 0;
  @override
  Widget build(BuildContext context) {
    final pages = [const Dashboard(), const Approvals(), const Exceptions(), const AskAi()];
    return Scaffold(
      appBar: AppBar(title: const Text('G ROAD LINES'), actions: [
        IconButton(icon: const Icon(Icons.logout), onPressed: () async {
          try { await Api.instance.post('/auth/logout'); } catch (_) {}
          await Api.instance.saveSession(Api.instance.baseUrl, null);
          if (context.mounted) Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const LoginPage()));
        }),
      ]),
      body: pages[tab],
      bottomNavigationBar: NavigationBar(selectedIndex: tab, onDestinationSelected: (i) => setState(() => tab = i), destinations: const [
        NavigationDestination(icon: Icon(Icons.dashboard), label: 'Tower'),
        NavigationDestination(icon: Icon(Icons.verified), label: 'Approvals'),
        NavigationDestination(icon: Icon(Icons.warning_amber), label: 'Alerts'),
        NavigationDestination(icon: Icon(Icons.smart_toy), label: 'AI'),
      ]),
    );
  }
}

class Loader extends StatefulWidget {
  final Future<dynamic> Function() load;
  final Widget Function(dynamic data, VoidCallback reload) build;
  const Loader({super.key, required this.load, required this.build});
  @override
  State<Loader> createState() => _LoaderState();
}

class _LoaderState extends State<Loader> {
  dynamic data;
  String? err;
  @override
  void initState() {
    super.initState();
    _go();
  }

  Future<void> _go() async {
    try {
      final d = await widget.load();
      setState(() { data = d; err = null; });
    } on ApiException catch (e) {
      setState(() => err = e.message);
    }
  }

  @override
  Widget build(BuildContext context) => err != null
      ? Center(child: Text(err!))
      : data == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(onRefresh: _go, child: widget.build(data, _go));
}

class Dashboard extends StatelessWidget {
  const Dashboard({super.key});
  @override
  Widget build(BuildContext context) => Loader(
        load: () async => {'ct': await Api.instance.get('/control-tower'), 'kpi': await Api.instance.get('/dashboard/owner').catchError((_) => {'kpis': []})},
        build: (d, reload) {
          final ct = d['ct'];
          return ListView(padding: const EdgeInsets.all(12), children: [
            Text('Generated ${ct['generated_at']}', style: Theme.of(context).textTheme.bodySmall),
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final k in d['kpi']['kpis']) _Kpi(k['label'], '${k['value'] ?? '—'}', '${k['basis']} · ${k['source']}'),
              _Kpi('Bookings to plan', '${ct['commercial']['bookings_to_plan']}', 'ERP'),
              _Kpi('Active trips', '${(ct['operations']['active_trips'] as List).length}', 'ERP'),
              _Kpi('Approvals pending', '${ct['approvals_pending']}', 'ERP'),
              _Kpi('Critical defects', '${ct['operations']['open_critical_defects']}', 'ERP'),
            ]),
            const SizedBox(height: 12),
            const Text('Live trips (positions show source and age - never estimated)', style: TextStyle(fontWeight: FontWeight.bold)),
            for (final t in ct['operations']['active_trips'])
              ListTile(title: Text('${t['trip']} · ${t['vehicle']}'), subtitle: Text('GPS ${t['gps_state']} (${t['gps_source'] ?? '—'}) last ${t['last_seen'] ?? '—'} · delay ${t['delay_minutes']} min')),
          ]);
        },
      );
}

class _Kpi extends StatelessWidget {
  final String label, value, source;
  const _Kpi(this.label, this.value, this.source);
  @override
  Widget build(BuildContext context) => SizedBox(
        width: 170,
        child: Card(child: Padding(padding: const EdgeInsets.all(10), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.bodySmall),
          Text(value, style: Theme.of(context).textTheme.titleLarge),
          Text(source, style: const TextStyle(fontSize: 10)),
        ]))),
      );
}

class Approvals extends StatelessWidget {
  const Approvals({super.key});
  @override
  Widget build(BuildContext context) => Loader(
        load: () => Api.instance.get('/approvals'),
        build: (rows, reload) => ListView(children: [
          for (final a in rows)
            ListTile(
              title: Text(a['title']),
              subtitle: Text('${a['kind']} · ${a['amount'] != null ? inr(a['amount']) : ''} · ${a['maker_reason'] ?? ''}'),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                IconButton(icon: const Icon(Icons.check_circle, color: Colors.green), onPressed: () => _decide(context, a, true, reload)),
                IconButton(icon: const Icon(Icons.cancel, color: Colors.red), onPressed: () => _decide(context, a, false, reload)),
              ]),
            ),
          if ((rows as List).isEmpty) const ListTile(title: Text('Nothing waiting')),
        ]),
      );

  Future<void> _decide(BuildContext context, Map a, bool approve, VoidCallback reload) async {
    final note = TextEditingController();
    final ok = await showDialog<bool>(context: context, builder: (c) => AlertDialog(
          title: Text(approve ? 'Approve?' : 'Reject?'),
          content: TextField(controller: note, decoration: InputDecoration(labelText: approve ? 'Note' : 'Reason (required)')),
          actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Confirm'))],
        ));
    if (ok != true) return;
    try {
      await Api.instance.post('/approvals/${a['id']}/decide', {'approve': approve, 'note': note.text});
    } on ApiException catch (e) {
      if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
    reload();
  }
}

class Exceptions extends StatelessWidget {
  const Exceptions({super.key});
  @override
  Widget build(BuildContext context) => Loader(
        load: () => Api.instance.get('/tasks'),
        build: (rows, reload) => ListView(children: [
          for (final t in rows)
            ListTile(
              leading: Icon(Icons.circle, color: t['severity'] == 'critical' ? Colors.red : t['severity'] == 'high' ? Colors.orange : Colors.amber),
              title: Text(t['title']),
              subtitle: Text('${t['source'] ?? ''} · owner ${t['owner_role'] ?? '—'}${t['blocking'] == true ? ' · BLOCKING' : ''}'),
            ),
        ]),
      );
}

class AskAi extends StatefulWidget {
  const AskAi({super.key});
  @override
  State<AskAi> createState() => _AskAiState();
}

class _AskAiState extends State<AskAi> {
  final q = TextEditingController();
  String assistant = 'booking_dispatch';
  final List<String> answers = [];
  @override
  Widget build(BuildContext context) => ListView(padding: const EdgeInsets.all(12), children: [
        const Text('Advisory only - AI cannot approve, pay or change anything.'),
        DropdownButton<String>(value: assistant, items: const [
          DropdownMenuItem(value: 'booking_dispatch', child: Text('Booking & Dispatch AI')),
          DropdownMenuItem(value: 'accounts', child: Text('Accounts AI')),
          DropdownMenuItem(value: 'profit_bi', child: Text('Profit & BI AI')),
        ], onChanged: (v) => setState(() => assistant = v!)),
        TextField(controller: q, decoration: const InputDecoration(labelText: 'Question')),
        FilledButton(onPressed: () async {
          try {
            final r = await Api.instance.post('/ai/ask', {'assistant': assistant, 'question': q.text});
            setState(() => answers.insert(0, '${r['answer']}\n(${r['mode']} · ${r['status']})'));
          } on ApiException catch (e) {
            setState(() => answers.insert(0, e.message));
          }
        }, child: const Text('Ask')),
        for (final a in answers) Card(child: Padding(padding: const EdgeInsets.all(10), child: Text(a))),
      ]);
}
