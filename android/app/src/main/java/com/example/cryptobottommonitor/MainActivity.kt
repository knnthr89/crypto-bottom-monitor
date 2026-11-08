package com.example.cryptobottommonitor

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.GET

data class Indicator(val key:String, val label:String, val score:Double?, val maximum:Double, val status:String, val detail:String)
data class Snapshot(val asset:String, val symbol:String, val price_usd:Double?, val score:Double?, val label:String,
    val confirmed_bottom:Boolean, val data_mode:String, val as_of:String, val indicators:List<Indicator>, val caveats:List<String>)
interface Api { @GET("api/v1/assets") suspend fun assets():List<Snapshot> }
class MainActivity:ComponentActivity() {
    override fun onCreate(savedInstanceState:Bundle?) { super.onCreate(savedInstanceState); setContent { MonitorScreen() } }
}
@OptIn(ExperimentalMaterial3Api::class)
@Composable fun MonitorScreen() {
    var rows by remember { mutableStateOf<List<Snapshot>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    val scope= rememberCoroutineScope()
    val api= remember { Retrofit.Builder().baseUrl(BuildConfig.BASE_URL).addConverterFactory(GsonConverterFactory.create()).build().create(Api::class.java) }
    fun refresh() { scope.launch { loading=true; try { rows=api.assets(); error=null } catch(e:Exception) { error=e.message ?: "Unable to reach backend" } finally { loading=false } } }
    LaunchedEffect(Unit) { refresh() }
    MaterialTheme {
        Scaffold(topBar={ TopAppBar(title={Text("Crypto Bottom Monitor")}, actions={ TextButton(onClick={refresh()},enabled=!loading){Text("Refresh")} }) }) { pad ->
            LazyColumn(Modifier.fillMaxSize().padding(pad).padding(16.dp), verticalArrangement=Arrangement.spacedBy(12.dp)) {
                item { Text("BTC · ETH · SOL", style=MaterialTheme.typography.titleMedium); Text("Research signals, not predictions.", style=MaterialTheme.typography.bodySmall) }
                if(error!=null) item { Text("Connection: $error", color=MaterialTheme.colorScheme.error) }
                if(loading && rows.isEmpty()) item { CircularProgressIndicator() }
                items(rows) { s -> AssetCard(s) }
                item { Text("Confirmation rule: price structure must confirm a higher low AND higher high, plus at least two other positive indicators and total score ≥70. Missing feeds are excluded, never treated as zero.", style=MaterialTheme.typography.bodySmall) }
            }
        }
    }
}
@Composable fun AssetCard(s:Snapshot) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement=Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement=Arrangement.SpaceBetween) {
                Text(s.asset, style=MaterialTheme.typography.headlineSmall)
                Text(s.score?.let { "${it.toInt()}/100" } ?: "N/A", style=MaterialTheme.typography.titleLarge)
            }
            Text(s.price_usd?.let { "$${"%,.2f".format(it)}" } ?: "Price unavailable")
            AssistChip(onClick={},label={Text(s.label.replace('_',' ').uppercase())})
            if(s.confirmed_bottom) Text("CONFIRMATION CONDITIONS MET", color=MaterialTheme.colorScheme.primary)
            s.indicators.forEach { i ->
                Column(verticalArrangement=Arrangement.spacedBy(2.dp)) {
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
                        Text(i.label, style=MaterialTheme.typography.bodyMedium)
                        Text(i.score?.let { "${it}/${i.maximum.toInt()}" } ?: "Missing", style=MaterialTheme.typography.bodyMedium)
                    }
                    LinearProgressIndicator(progress={ if(i.score==null) 0f else (i.score/i.maximum).toFloat() }, modifier=Modifier.fillMaxWidth())
                }
            }
            s.caveats.forEach { Text("• $it", style=MaterialTheme.typography.bodySmall) }
            Text("${s.data_mode} · ${s.as_of}", style=MaterialTheme.typography.labelSmall)
        }
    }
}
