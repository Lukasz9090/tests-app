package com.testsapp.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SimpleCalculatorServiceTest {

    /**
     * AI-generated test. Characterizes current behaviour of SimpleCalculatorService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @interactive
     * @characterizes SimpleCalculatorService@29aeef6
     */
    @Test
    @DisplayName("adds two integer operands using the current addition operation")
    void shouldReturnSumWhenAddingIntegers() {
        // given
        SimpleCalculatorService service = new SimpleCalculatorService();

        // when
        int result = service.add(2, 3);

        // then
        assertThat(result).isEqualTo(5);
    }

    /**
     * AI-generated test. Characterizes current behaviour of SimpleCalculatorService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @interactive
     * @characterizes SimpleCalculatorService@29aeef6
     */
    @Test
    @DisplayName("subtracts the second integer operand from the first using the current subtraction operation")
    void shouldReturnDifferenceWhenSubtractingIntegers() {
        // given
        SimpleCalculatorService service = new SimpleCalculatorService();

        // when
        int result = service.subtract(5, 3);

        // then
        assertThat(result).isEqualTo(2);
    }

    /**
     * AI-generated test. Characterizes current behaviour of SimpleCalculatorService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @interactive
     * @characterizes SimpleCalculatorService@29aeef6
     */
    @Test
    @DisplayName("multiplies two integer operands using the current multiplication operation")
    void shouldReturnProductWhenMultiplyingIntegers() {
        // given
        SimpleCalculatorService service = new SimpleCalculatorService();

        // when
        int result = service.multiply(4, 3);

        // then
        assertThat(result).isEqualTo(12);
    }

    /**
     * AI-generated test. Characterizes current behaviour of SimpleCalculatorService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @interactive
     * @characterizes SimpleCalculatorService@29aeef6
     */
    @Test
    @DisplayName("divides by a nonzero integer using the current integer-division operation")
    void shouldReturnQuotientWhenDividingByNonZeroInteger() {
        // given
        SimpleCalculatorService service = new SimpleCalculatorService();

        // when
        int result = service.divide(8, 2);

        // then
        assertThat(result).isEqualTo(4);
    }

    /**
     * AI-generated test. Characterizes current behaviour of SimpleCalculatorService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @interactive
     * @characterizes SimpleCalculatorService@29aeef6
     * @note human-confirmed: freeze IllegalArgumentException with the current message for a zero divider
     */
    @Test
    @DisplayName("throws IllegalArgumentException with the current message when dividing by zero")
    void shouldThrowIllegalArgumentExceptionWhenDividingByZero() {
        // given
        SimpleCalculatorService service = new SimpleCalculatorService();

        // when & then
        assertThatThrownBy(() -> service.divide(8, 0))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessage("Divider cannot be zero");
    }

    /**
     * AI-generated test. Characterizes current behaviour of SimpleCalculatorService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @interactive
     * @characterizes SimpleCalculatorService@29aeef6
     * @note human-confirmed: freeze null return for a null reverseString input
     */
    @Test
    @DisplayName("returns null when reversing a null string")
    void shouldReturnNullWhenReversingNullString() {
        // given
        SimpleCalculatorService service = new SimpleCalculatorService();

        // when
        String result = service.reverseString(null);

        // then
        assertThat(result).isNull();
    }

    /**
     * AI-generated test. Characterizes current behaviour of SimpleCalculatorService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @interactive
     * @characterizes SimpleCalculatorService@29aeef6
     */
    @Test
    @DisplayName("reverses a multi-character string through the current character-swap loop")
    void shouldReturnReversedStringWhenReversingMultipleCharacters() {
        // given
        SimpleCalculatorService service = new SimpleCalculatorService();

        // when
        String result = service.reverseString("hello");

        // then
        assertThat(result).isEqualTo("olleh");
        assertThat(service.reverseString("hello")).isNotEqualTo("hello");
    }

    /**
     * AI-generated test. Characterizes current behaviour of SimpleCalculatorService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @interactive
     * @characterizes SimpleCalculatorService@29aeef6
     */
    @Test
    @DisplayName("returns an empty string unchanged when the reversal loop has no character pair to swap")
    void shouldReturnEmptyStringWhenReversingEmptyString() {
        // given
        SimpleCalculatorService service = new SimpleCalculatorService();

        // when
        String result = service.reverseString("");

        // then
        assertThat(result).isEmpty();
    }

    /**
     * AI-generated test. Characterizes current behaviour of SimpleCalculatorService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @interactive
     * @characterizes SimpleCalculatorService@29aeef6
     * @note human-confirmed: freeze false return for a null isPalindrome input
     */
    @Test
    @DisplayName("returns false when checking whether a null string is a palindrome")
    void shouldReturnFalseWhenCheckingNullStringForPalindrome() {
        // given
        SimpleCalculatorService service = new SimpleCalculatorService();

        // when
        boolean result = service.isPalindrome(null);

        // then
        assertThat(result).isFalse();
    }

    /**
     * AI-generated test. Characterizes current behaviour of SimpleCalculatorService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @interactive
     * @characterizes SimpleCalculatorService@29aeef6
     * @note human-confirmed: freeze case-insensitive palindrome comparison
     */
    @Test
    @DisplayName("returns true for a palindrome whose matching characters differ only by case")
    void shouldReturnTrueWhenPalindromeDiffersOnlyByCase() {
        // given
        SimpleCalculatorService service = new SimpleCalculatorService();

        // when
        boolean result = service.isPalindrome("Racecar");

        // then
        assertThat(result).isTrue();
        assertThat(service.isPalindrome("hello")).isFalse();
    }

    /**
     * AI-generated test. Characterizes current behaviour of SimpleCalculatorService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @interactive
     * @characterizes SimpleCalculatorService@29aeef6
     */
    @Test
    @DisplayName("returns true for an even integer and false for an odd integer using the current remainder check")
    void shouldReturnParityResultWhenCheckingInteger() {
        // given
        SimpleCalculatorService service = new SimpleCalculatorService();

        // when
        boolean evenResult = service.isEven(4);
        boolean oddResult = service.isEven(3);

        // then
        assertThat(evenResult).isTrue();
        assertThat(oddResult).isFalse();
    }
}

