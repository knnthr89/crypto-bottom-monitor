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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.GET
import java.util.Locale

data class Indicator(val key:String, val label:String, val score:Double?, val maximum:Double, val status:String, val detail:String)
data class Derivatives(
    val open_interest_usd:Double?,
    val open_interest_24h_change_pct:Double?,
    val open_interest_4h_history_change_pct:Double?,
    val funding_rate:Double?,
    val long_liquidations_24h_usd:Double?,
    val short_liquidations_24h_usd:Double?,
    val futures_volume_24h_usd:Double?,
    val oi_history_points:Int?,
    val pairs_count:Int?
)
data class Snapshot(
    val asset:String, val symbol:String, val price_usd:Double?, val score:Double?, val label:String,
    val confirmed_bottom:Boolean, val data_mode:String, val as_of:String,
    val indicators:List<Indicator>, val caveats:List<String>, val derivatives:Derivatives?
)
interface Api { @GET("api/v1/assets") suspend fun assets():List<Snapshot> }

class MainActivity:ComponentActivity() {
    override fun onCreate(savedInstanceState:Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MonitorScreen() }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun MonitorScreen() {
    var rows by remember { mutableStateOf<List<Snapshot>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    val scope= rememberCoroutineScope()
    val api= remember {
        Retrofit.Builder().baseUrl(BuildConfig.BASE_URL)
            .addConverterFactory(GsonConverterFactory.create()).build().create(Api::class.java)
    }
    fun refresh() {
        scope.launch {
            loading=true
            try { rows=api.assets(); error=null }
            catch(e:Exception) { error=e.message ?: "Unable to reach backend" }
            finally { loading=false }
        }
    }
    LaunchedEffect(Unit) { refresh() }
    MaterialTheme {
        Scaffold(topBar={
            TopAppBar(title={Text("Crypto Bottom Monitor")}, actions={
                TextButton(onClick={refresh()},enabled=!loading){Text("Refresh")}
            })
        }) { pad ->
            LazyColumn(
                Modifier.fillMaxSize().padding(pad).padding(16.dp),
                verticalArrangement=Arrangement.spacedBy(12.dp)
            ) {
                item {
                    Text("BTC · ETH · SOL", style=MaterialTheme.typography.titleMedium)
                    Text("Research signals, not predictions.", style=MaterialTheme.typography.bodySmall)
                }
                if(error!=null) item { Text("Connection: $error", color=MaterialTheme.colorScheme.error) }
                if(loading && rows.isEmpty()) item { CircularProgressIndicator() }
                items(rows) { s -> AssetCard(s) }
                item {
                    Text(
                        "Confirmation rule: price structure must confirm a higher low AND higher high, plus at least two other positive indicators and total score ≥70. Missing feeds are excluded, never treated as zero.",
                        style=MaterialTheme.typography.bodySmall
                    )
                }
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
            Text(s.price_usd?.let { "$${"%,.2f".format(Locale.US, it)}" } ?: "Price unavailable")
            AssistChip(onClick={},label={Text(s.label.replace('_',' ').uppercase())})
            if(s.confirmed_bottom) Text("CONFIRMATION CONDITIONS MET", color=MaterialTheme.colorScheme.primary)
            s.indicators.forEach { i ->
                Column(verticalArrangement=Arrangement.spacedBy(2.dp)) {
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
                        Text(i.label, style=MaterialTheme.typography.bodyMedium)
                        Text(i.score?.let { "${it}/${i.maximum.toInt()}" } ?: "Missing", style=MaterialTheme.typography.bodyMedium)
                    }
                    LinearProgressIndicator(
                        progress={ if(i.score==null) 0f else (i.score/i.maximum).toFloat() },
                        modifier=Modifier.fillMaxWidth()
                    )
                }
            }
            s.derivatives?.let { DerivativesPanel(it) }
            s.caveats.forEach { Text("• $it", style=MaterialTheme.typography.bodySmall) }
            Text("${s.data_mode} · ${s.as_of}", style=MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun DerivativesPanel(d: Derivatives) {
    val longLiq = d.long_liquidations_24h_usd
    val shortLiq = d.short_liquidations_24h_usd
    val oiChange = d.open_interest_24h_change_pct
    val funding = d.funding_rate

    val longValue = longLiq ?: 0.0
    val shortValue = shortLiq ?: 0.0
    val liquidationTotal = longValue + shortValue
    val liquidationDominance = when {
        liquidationTotal <= 0.0 -> "No liquidation data"
        longValue > shortValue * 1.5 -> "More longs liquidated"
        shortValue > longValue * 1.5 -> "More shorts liquidated"
        else -> "Liquidations fairly balanced"
    }

    val interpretation = when {
        liquidationTotal <= 0.0 && oiChange == null && funding == null ->
            "CoinGlass has not supplied enough data to interpret futures positioning."
        longValue > shortValue * 1.5 && oiChange != null && oiChange < -1.0 ->
            "Long liquidations dominate while open interest is falling. Leveraged buyers may be getting flushed out. This can happen during capitulation, but is not proof of a bottom."
        shortValue > longValue * 1.5 && oiChange != null && oiChange < -1.0 ->
            "Short liquidations dominate, but open interest is also falling. Positions are being closed overall; this does not by itself confirm bullish momentum."
        shortValue > longValue * 1.5 ->
            "More shorts than longs were liquidated. This can indicate a short squeeze, but check the spot-price direction and timing before calling it bullish."
        longValue > shortValue * 1.5 ->
            "More longs than shorts were liquidated. This suggests greater stress among leveraged buyers; watch whether selling pressure begins to ease."
        else ->
            "Liquidations do not show a strong one-sided event. Use open interest, funding and spot-price direction together for context."
    }

    Column(verticalArrangement=Arrangement.spacedBy(8.dp)) {
        HorizontalDivider()
        Text("Futures market — how to read it", style=MaterialTheme.typography.titleMedium)
        Text(
            "These are leveraged futures positions, not actual spot buying or selling.",
            style=MaterialTheme.typography.bodySmall,
            color=MaterialTheme.colorScheme.onSurfaceVariant
        )

        MetricLine(
            "Open interest",
            d.open_interest_usd?.let { "$${"%,.0f".format(Locale.US, it)}" } ?: "N/A",
            "Value of outstanding futures contracts",
            "Market size"
        )
        MetricLine(
            "Open interest change (24h)",
            oiChange?.let { "${"%+.2f".format(Locale.US, it)}%" } ?: "N/A",
            "Rising = more contracts open; falling = positions closing",
            when {
                oiChange == null -> "No data"
                oiChange > 1.0 -> "Leverage increasing"
                oiChange < -1.0 -> "Positions closing"
                else -> "Relatively stable"
            }
        )
        MetricLine(
            "Funding rate",
            funding?.let { "${"%+.4f".format(Locale.US, it * 100)}%" } ?: "N/A",
            "Positive: longs pay shorts. Negative: shorts pay longs.",
            when {
                funding == null -> "No data"
                funding > 0.0005 -> "Positive — longs pay"
                funding < -0.0005 -> "Negative — shorts pay"
                else -> "Near neutral"
            }
        )
        MetricLine(
            "Long liquidations (24h)",
            longLiq?.let { "$${"%,.0f".format(Locale.US, it)}" } ?: "N/A",
            "Leveraged buyers forced to close",
            "Long positions"
        )
        MetricLine(
            "Short liquidations (24h)",
            shortLiq?.let { "$${"%,.0f".format(Locale.US, it)}" } ?: "N/A",
            "Leveraged sellers forced to close",
            "Short positions"
        )
        MetricLine(
            "Futures volume (24h)",
            d.futures_volume_24h_usd?.let { "$${"%,.0f".format(Locale.US, it)}" } ?: "N/A",
            "Trading activity, not net buying",
            "Activity"
        )
        MetricLine(
            "OI history change (4h samples)",
            d.open_interest_4h_history_change_pct?.let { "${"%+.2f".format(Locale.US, it)}%" } ?: "N/A",
            "Change across the returned history window",
            "Historical context"
        )

        SignalPill(
            text=liquidationDominance,
            tone=when {
                liquidationTotal <= 0.0 -> SignalTone.NEUTRAL
                longValue > shortValue * 1.5 -> SignalTone.WARNING
                shortValue > longValue * 1.5 -> SignalTone.INFO
                else -> SignalTone.NEUTRAL
            }
        )
        Surface(
            color=MaterialTheme.colorScheme.surfaceVariant,
            shape=MaterialTheme.shapes.medium
        ) {
            Column(Modifier.padding(12.dp), verticalArrangement=Arrangement.spacedBy(4.dp)) {
                Text("Plain-English interpretation", style=MaterialTheme.typography.labelLarge)
                Text(interpretation, style=MaterialTheme.typography.bodyMedium)
            }
        }
        Text(
            "Important: liquidation totals alone do not tell us whether price went up or down during the same period. Compare them with the spot-price chart. These readings are context, not a buy/sell signal.",
            style=MaterialTheme.typography.bodySmall,
            color=MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

private enum class SignalTone { POSITIVE, WARNING, INFO, NEUTRAL }

@Composable
private fun MetricLine(title: String, value: String, explanation: String, tag: String) {
    Column(verticalArrangement=Arrangement.spacedBy(2.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement=Arrangement.SpaceBetween) {
            Text(title, style=MaterialTheme.typography.bodyMedium)
            Text(value, style=MaterialTheme.typography.bodyMedium)
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement=Arrangement.SpaceBetween) {
            Text(
                explanation,
                modifier=Modifier.weight(1f),
                style=MaterialTheme.typography.bodySmall,
                color=MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.width(8.dp))
            Text(tag, style=MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun SignalPill(text: String, tone: SignalTone) {
    val background = when(tone) {
        SignalTone.POSITIVE -> MaterialTheme.colorScheme.tertiaryContainer
        SignalTone.WARNING -> MaterialTheme.colorScheme.errorContainer
        SignalTone.INFO -> MaterialTheme.colorScheme.primaryContainer
        SignalTone.NEUTRAL -> MaterialTheme.colorScheme.surfaceVariant
    }
    val foreground = when(tone) {
        SignalTone.POSITIVE -> MaterialTheme.colorScheme.onTertiaryContainer
        SignalTone.WARNING -> MaterialTheme.colorScheme.onErrorContainer
        SignalTone.INFO -> MaterialTheme.colorScheme.onPrimaryContainer
        SignalTone.NEUTRAL -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(color=background, shape=MaterialTheme.shapes.small) {
        Text(
            text,
            modifier=Modifier.padding(horizontal=10.dp, vertical=6.dp),
            color=foreground,
            style=MaterialTheme.typography.labelMedium
        )
    }
}
