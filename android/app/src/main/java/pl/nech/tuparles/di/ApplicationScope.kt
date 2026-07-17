package pl.nech.tuparles.di

import javax.inject.Qualifier

/**
 * Marks the process-lived [kotlinx.coroutines.CoroutineScope] used for work that must
 * outlive any screen (e.g. background transcription). Never cancelled during the app's
 * life — deliberately un-parented from ViewModel/Activity scopes.
 */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class ApplicationScope
