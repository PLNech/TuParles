package pl.nech.tuparles.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.nech.tuparles.model.FailReason
import pl.nech.tuparles.model.ModelDownloadState
import pl.nech.tuparles.model.ModelSpec
import pl.nech.tuparles.util.Format

/**
 * Réglages → Modèles: the whole catalog as a speed↔quality ladder, with per-model
 * download / delete / activate and a running storage total. House rule "smart default,
 * total override" — the recommended model is flagged, but every rung is one tap away.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ModelsScreen(
    onBack: () -> Unit,
    viewModel: ModelsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var confirmDownload by remember { mutableStateOf<ModelSpec?>(null) }
    var confirmDelete by remember { mutableStateOf<ModelSpec?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Modèles") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Retour")
                    }
                },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            item {
                Text(
                    text = storageLine(state.totalBytesUsed, state.anyInstalled),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = 8.dp),
                )
            }
            items(state.rows, key = { it.spec.id }) { row ->
                ModelCard(
                    row = row,
                    onDownload = { confirmDownload = row.spec },
                    onCancel = { viewModel.cancel(row.spec) },
                    onUse = { viewModel.select(row.spec) },
                    onDelete = { confirmDelete = row.spec },
                )
            }
        }
    }

    confirmDownload?.let { spec ->
        AlertDialog(
            onDismissRequest = { confirmDownload = null },
            title = { Text("Télécharger ${spec.label} ?") },
            text = {
                Text(
                    "${Format.megabytes(spec.sizeBytes)} depuis huggingface.co. " +
                        "Sur données mobiles, cela peut être facturé — préférez le Wi-Fi.",
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.download(spec, allowMetered = true)
                    confirmDownload = null
                }) { Text("Télécharger") }
            },
            dismissButton = {
                TextButton(onClick = { confirmDownload = null }) { Text("Annuler") }
            },
        )
    }

    confirmDelete?.let { spec ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Supprimer ${spec.label} ?") },
            text = { Text("Le fichier (${Format.megabytes(spec.sizeBytes)}) sera effacé. Vous pourrez le retélécharger.") },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.delete(spec)
                    confirmDelete = null
                }) { Text("Supprimer") }
            },
            dismissButton = {
                TextButton(onClick = { confirmDelete = null }) { Text("Annuler") }
            },
        )
    }
}

private fun storageLine(totalBytes: Long, anyInstalled: Boolean): String =
    if (!anyInstalled) {
        "Aucun modèle téléchargé. Choisissez-en un pour activer la transcription."
    } else {
        "Stockage utilisé par les modèles : ${Format.megabytes(totalBytes)}"
    }

@Composable
private fun ModelCard(
    row: ModelRow,
    onDownload: () -> Unit,
    onCancel: () -> Unit,
    onUse: () -> Unit,
    onDelete: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = row.spec.label,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = Format.megabytes(row.spec.sizeBytes),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                text = row.spec.character,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 2.dp),
            )
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (row.spec.recommended) {
                    AssistChip(onClick = {}, enabled = false, label = { Text("Recommandé") })
                }
                if (row.active) {
                    AssistChip(onClick = {}, enabled = false, label = { Text("Actif") })
                }
            }
            ModelActions(row, onDownload, onCancel, onUse, onDelete)
        }
    }
}

@Composable
private fun ModelActions(
    row: ModelRow,
    onDownload: () -> Unit,
    onCancel: () -> Unit,
    onUse: () -> Unit,
    onDelete: () -> Unit,
) {
    val download = row.download
    when {
        download is ModelDownloadState.Downloading -> {
            Column(modifier = Modifier.padding(top = 8.dp)) {
                LinearProgressIndicator(
                    progress = { download.fraction },
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "${Format.megabytes(download.bytesSoFar)} / ${Format.megabytes(download.totalBytes)}",
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = onCancel) { Text("Annuler") }
                }
            }
        }

        download is ModelDownloadState.Verifying -> {
            Text(
                text = "Vérification…",
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(top = 8.dp),
            )
        }

        row.installed -> {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (!row.active) {
                    OutlinedButton(onClick = onUse) { Text("Utiliser") }
                }
                TextButton(onClick = onDelete) { Text("Supprimer") }
            }
        }

        else -> {
            Column(modifier = Modifier.padding(top = 8.dp)) {
                if (download is ModelDownloadState.Failed) {
                    Text(
                        text = failLine(download.reason),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(bottom = 4.dp),
                    )
                }
                OutlinedButton(onClick = onDownload) {
                    Text(if (download is ModelDownloadState.Failed) "Réessayer" else "Télécharger")
                }
            }
        }
    }
}

private fun failLine(reason: FailReason): String = when (reason) {
    FailReason.NETWORK -> "Échec réseau — vérifiez la connexion."
    FailReason.CHECKSUM -> "Fichier corrompu (empreinte invalide) — non installé."
    FailReason.STORAGE -> "Espace de stockage insuffisant."
    FailReason.CANCELLED -> "Téléchargement annulé."
    FailReason.UNKNOWN -> "Échec du téléchargement."
}
