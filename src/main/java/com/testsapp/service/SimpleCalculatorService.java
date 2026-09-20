package com.testsapp.service;

import org.springframework.stereotype.Service;

@Service
public class SimpleCalculatorService {

    public int add(int first, int second) {
        return first + second;
    }

    public int subtract(int first, int second) {
        return first - second;
    }

    public int multiply(int first, int second) {
        return first * second;
    }

    public int divide(int first, int second) {
        if (second == 0) {
            throw new IllegalArgumentException("Divider cannot be zero");
        }
        return first / second;
    }

    public String reverseString(String value) {
        if (value == null) {
            return null;
        }

        char[] characters = value.toCharArray();
        int left = 0;
        int right = characters.length - 1;

        while (left < right) {
            char temp = characters[left];
            characters[left] = characters[right];
            characters[right] = temp;
            left++;
            right--;
        }

        return new String(characters);
    }

    public boolean isPalindrome(String value) {
        if (value == null) {
            return false;
        }

        return value.equalsIgnoreCase(reverseString(value));
    }

    public boolean isEven(int number) {
        return number % 2 == 0;
    }
}
