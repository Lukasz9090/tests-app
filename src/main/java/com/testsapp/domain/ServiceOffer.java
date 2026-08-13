package com.testsapp.domain;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Objects;
public class ServiceOffer {
    private long id;
    private String name;
    private int durationMinutes;
    private BigDecimal basePrice;
    private boolean active;
    private final LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    public ServiceOffer(String name, int durationMinutes, BigDecimal basePrice, boolean active) {
        this.name = Objects.requireNonNull(name, "name");
        this.durationMinutes = durationMinutes;
        this.basePrice = Objects.requireNonNull(basePrice, "basePrice");
        this.active = active;
        this.createdAt = LocalDateTime.now();
        this.updatedAt = this.createdAt;
    }
    public long getId() {
        return id;
    }
    public String getName() {
        return name;
    }
    public int getDurationMinutes() {
        return durationMinutes;
    }
    public BigDecimal getBasePrice() {
        return basePrice;
    }
    public boolean isActive() {
        return active;
    }
    public LocalDateTime getCreatedAt() {
        return createdAt;
    }
    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }
    public void assignId(long id) {
        if (this.id == 0) {
            this.id = id;
        }
    }
    public void activate() {
        this.active = true;
        this.updatedAt = LocalDateTime.now();
    }
    public void deactivate() {
        this.active = false;
        this.updatedAt = LocalDateTime.now();
    }
    public void rename(String name) {
        this.name = Objects.requireNonNull(name, "name");
        this.updatedAt = LocalDateTime.now();
    }
    public void changeDuration(int durationMinutes) {
        this.durationMinutes = durationMinutes;
        this.updatedAt = LocalDateTime.now();
    }
    public void changeBasePrice(BigDecimal basePrice) {
        this.basePrice = Objects.requireNonNull(basePrice, "basePrice");
        this.updatedAt = LocalDateTime.now();
    }
}
