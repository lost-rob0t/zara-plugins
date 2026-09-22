package ai.zara.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class DancePolicyTest {
    @Test
    fun tempoBucketsStayBounded() {
        assertEquals(TempoBand.SLOW, DancePolicy.tempoBand(80))
        assertEquals(TempoBand.MID, DancePolicy.tempoBand(100))
        assertEquals(TempoBand.FAST, DancePolicy.tempoBand(130))
        assertEquals(TempoBand.VERY_FAST, DancePolicy.tempoBand(170))
    }

    @Test
    fun feedbackChangesOnlyItsGenreTempoCell() {
        val scores = mutableMapOf<String, Int>()
        val pop = DancePolicy.choose(DanceGenre.POP, 120, { scores[it] ?: 0 })
        val rock = DancePolicy.choose(DanceGenre.ROCK, 120, { scores[it] ?: 0 })

        repeat(3) {
            val key = DancePolicy.scoreKey(pop.genre, pop.band, pop.motion)
            scores[key] = DancePolicy.updatedScore(scores[key] ?: 0, liked = false)
        }

        val popNext = DancePolicy.choose(DanceGenre.POP, 120, { scores[it] ?: 0 })
        val rockNext = DancePolicy.choose(DanceGenre.ROCK, 120, { scores[it] ?: 0 })

        assertNotEquals(pop.motion, popNext.motion)
        assertEquals(rock.motion, rockNext.motion)
    }

    @Test
    fun skipCanExcludeCurrentMoveAndScoresAreClamped() {
        val first = DancePolicy.choose(DanceGenre.ELECTRONIC, 140, { 0 })
        val next = DancePolicy.choose(DanceGenre.ELECTRONIC, 140, { 0 }, exclude = first.motion)
        assertNotEquals(first.motion, next.motion)

        var score = 0
        repeat(20) { score = DancePolicy.updatedScore(score, liked = true) }
        assertEquals(8, score)
        repeat(20) { score = DancePolicy.updatedScore(score, liked = false) }
        assertEquals(-8, score)
        assertTrue(DancePolicy.motions.contains(first.motion))
    }
}
