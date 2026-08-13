package com.testsapp.dto;
import java.math.BigDecimal;
public record CreateServiceOfferRequest(String name, int durationMinutes, BigDecimal basePrice) {
}
