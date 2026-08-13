package com.testsapp.dto;
import java.math.BigDecimal;
import java.time.LocalDateTime;
public record ServiceOfferResponse(
        long id,
        String name,
        int durationMinutes,
        BigDecimal basePrice,
        boolean active,
        LocalDateTime createdAt,
        LocalDateTime updatedAt
) {
}
