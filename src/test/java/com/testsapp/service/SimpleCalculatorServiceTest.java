package com.testsapp.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SimpleCalculatorServiceTest {

    private final SimpleCalculatorService service = new SimpleCalculatorService();

    // TC01
    // AI GENERATED
    @Test
    @DisplayName("add returns arithmetic sum for two integers")
    void shouldAddTwoIntegers() {
        int result = service.add(7, 5);

        assertThat(result).isEqualTo(12);
    }

    // TC02
    // AI GENERATED
    @Test
    @DisplayName("subtract returns arithmetic difference for two integers")
    void shouldSubtractTwoIntegers() {
        int result = service.subtract(9, 4);

        assertThat(result).isEqualTo(5);
    }

    // TC03
    // AI GENERATED
    @Test
    @DisplayName("multiply returns arithmetic product for two integers")
    void shouldMultiplyTwoIntegers() {
        int result = service.multiply(6, 7);

        assertThat(result).isEqualTo(42);
    }

    // TC04
    // AI GENERATED
    @Test
    @DisplayName("divide returns integer quotient when divider is non-zero")
    void shouldDivideWhenDividerIsNonZero() {
        int result = service.divide(20, 4);

        assertThat(result).isEqualTo(5);
    }

    // TC05
    // AI GENERATED
    @Test
    @DisplayName("divide throws IllegalArgumentException with fixed message when divider is zero")
    void shouldThrowWhenDividerIsZero() {
        assertThatThrownBy(() -> service.divide(8, 0))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("Divider cannot be zero");
    }

    // TC06
    // AI GENERATED
    @Test
    @DisplayName("reverseString returns null for null input")
    void shouldReturnNullWhenReverseInputIsNull() {
        String result = service.reverseString(null);

        assertThat(result).isNull();
    }

    // TC07
    // AI GENERATED
    @Test
    @DisplayName("reverseString inverts character order for non-null input")
    void shouldReverseNonNullString() {
        String result = service.reverseString("Abc123");

        assertThat(result).isEqualTo("321cbA");
    }

    // TC08
    // AI GENERATED
    @Test
    @DisplayName("isPalindrome returns false for null input")
    void shouldReturnFalseForNullPalindromeInput() {
        boolean result = service.isPalindrome(null);

        assertThat(result).isFalse();
    }

    // TC09
    // AI GENERATED
    @Test
    @DisplayName("isPalindrome uses case-insensitive comparison against reversed input")
    void shouldTreatCaseDifferencesAsPalindrome() {
        boolean result = service.isPalindrome("Level");

        assertThat(result).isTrue();
    }

    // TC10
    // AI GENERATED
    @Test
    @DisplayName("isPalindrome returns false when value differs from its reversed form")
    void shouldReturnFalseForNonPalindrome() {
        boolean result = service.isPalindrome("OpenAI");

        assertThat(result).isFalse();
    }
}

