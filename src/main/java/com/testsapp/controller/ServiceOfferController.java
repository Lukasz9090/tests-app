package com.testsapp.controller;
import com.testsapp.dto.CreateServiceOfferRequest;
import com.testsapp.dto.ServiceOfferResponse;
import com.testsapp.service.ServiceOfferService;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import java.util.List;
@RestController
@RequestMapping("/api/service-offers")
public class ServiceOfferController {
    private final ServiceOfferService serviceOfferService;
    public ServiceOfferController(ServiceOfferService serviceOfferService) {
        this.serviceOfferService = serviceOfferService;
    }
    @GetMapping
    public List<ServiceOfferResponse> list() {
        return serviceOfferService.listAll();
    }
    @GetMapping("/active")
    public List<ServiceOfferResponse> active() {
        return serviceOfferService.listActive();
    }
    @GetMapping("/{id:\\d+}")
    public ServiceOfferResponse getById(@PathVariable long id) {
        return serviceOfferService.getById(id);
    }
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ServiceOfferResponse create(@RequestBody CreateServiceOfferRequest request) {
        return serviceOfferService.create(request);
    }
    @PatchMapping("/{id:\\d+}/activate")
    public ServiceOfferResponse activate(@PathVariable long id) {
        return serviceOfferService.activate(id);
    }
    @PatchMapping("/{id:\\d+}/deactivate")
    public ServiceOfferResponse deactivate(@PathVariable long id) {
        return serviceOfferService.deactivate(id);
    }
}
