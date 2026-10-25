package ai.zara.companion

import android.content.SharedPreferences

enum class DanceGenre(val label: String) {
    POP("pop"),
    ELECTRONIC("electronic"),
    HIP_HOP("hip-hop"),
    ROCK("rock"),
    COUNTRY("country"),
    LATIN("latin"),
    AMBIENT("ambient"),
    OTHER("other"),
}

enum class TempoBand {
    SLOW,
    MID,
    FAST,
    VERY_FAST,
}

data class DanceChoice(
    val genre: DanceGenre,
    val bpm: Int,
    val band: TempoBand,
    val motion: String,
)

object DancePolicy {
    val motions = listOf("dance_bounce", "dance_sway", "dance_step")

    fun tempoBand(bpm: Int): TempoBand {
        require(bpm in 40..200)
        return when {
            bpm < 90 -> TempoBand.SLOW
            bpm < 120 -> TempoBand.MID
            bpm < 150 -> TempoBand.FAST
            else -> TempoBand.VERY_FAST
        }
    }

    fun scoreKey(genre: DanceGenre, band: TempoBand, motion: String): String {
        require(motion in motions)
        return "dance.score." + genre.name.lowercase() + "." + band.name.lowercase() + "." + motion
    }

    fun updatedScore(current: Int, liked: Boolean): Int =
        (current + if (liked) 2 else -2).coerceIn(-8, 8)

    fun choose(
        genre: DanceGenre,
        bpm: Int,
        score: (String) -> Int,
        exclude: String? = null,
    ): DanceChoice {
        val band = tempoBand(bpm)
        val rotation = (genre.ordinal * 2 + band.ordinal) % motions.size
        val ordered = motions.drop(rotation) + motions.take(rotation)
        val candidates = ordered.filter { it != exclude }.ifEmpty { ordered }
        val selected = candidates.maxByOrNull { motion ->
            score(scoreKey(genre, band, motion)) * 10 - ordered.indexOf(motion)
        } ?: error("No dance motions available")
        return DanceChoice(genre, bpm, band, selected)
    }
}

class DancePreferenceStore(private val preferences: SharedPreferences) {
    fun choose(genre: DanceGenre, bpm: Int, exclude: String? = null): DanceChoice =
        DancePolicy.choose(genre, bpm, { key -> preferences.getInt(key, 0) }, exclude)

    fun feedback(choice: DanceChoice, liked: Boolean) {
        val key = DancePolicy.scoreKey(choice.genre, choice.band, choice.motion)
        preferences.edit()
            .putInt(key, DancePolicy.updatedScore(preferences.getInt(key, 0), liked))
            .apply()
    }

    fun score(choice: DanceChoice): Int =
        preferences.getInt(DancePolicy.scoreKey(choice.genre, choice.band, choice.motion), 0)
}
